"""
AI Chatbot with MCP tool-calls loop
-------------------------------------
The chatbot is powered by OpenAI GPT-4o.  It has access to all Jira MCP tools
via a synchronous MCP client.  Each user message triggers a tool-calls loop:

  1. Send user message + tool definitions to OpenAI.
  2. If OpenAI returns tool_calls, execute them against the MCP server.
  3. Feed results back to OpenAI for the final answer.
  4. Repeat until no more tool calls.

Usage from Streamlit:
    from chatbot import JiraChatbot
    bot = JiraChatbot()
    reply, tool_log = bot.chat("How many points did Josh team complete?")
"""

import json
import logging
from typing import Any

import openai

import config
from mcp_client import call_tool, list_tools

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Jira reporting assistant for a software team.
You have access to live Jira data through tool calls.

Context:
- Josh Team developers: {josh_team}
- Client Team developers: {client_team}
- Jira project: {project}
- Team matching and all person-related metrics use the **Developer** custom field only (developerName in tool results). **Assignee is never used** — do not rely on assignee in JQL or explanations.

CRITICAL — Always break down results by Developer Name:
- Whenever you present sprint data, story points, issue lists, team performance, or any
  quantitative answer, **always group and display results per developer** (by developerName).
- Show each developer's name, their issues, planned points, completed points, and remaining
  points in every answer — not just totals or "done vs not-done" summaries.
- For team summaries, list every developer under that team with their individual numbers,
  then show the team total.
- Never give only team-level or status-level aggregates without the per-developer breakdown.

Guidelines:
- For "who is on this ticket" or team filters, use **developerName** from tool output only; never infer from assignee.
- If you use search_issues with JQL, do not use `assignee = ...` for developer workload; prefer get_sprint_issues / get_team_comparison or JQL on the Developer field if your project exposes it (e.g. cf[10084] or "Developer" depending on instance).
- Always use tools to fetch live data before answering quantitative questions.
- When asked to generate a report, call generate_sprint_report and present the results clearly.
- When asked to compare teams, call get_team_comparison.
- When asked about velocity or trends, call get_team_velocity.
- Format numbers cleanly. Use tables or bullet points grouped by developer name.
- Be concise but complete. Every answer must include the developer-level breakdown.
""".format(
    josh_team=", ".join(config.JOSH_TEAM_MEMBERS) or "not configured yet",
    client_team=", ".join(config.CLIENT_TEAM_MEMBERS) or "not configured yet",
    project=config.JIRA_PROJECT_KEY,
)


class JiraChatbot:
    """Stateful chatbot that maintains conversation history."""

    def __init__(self) -> None:
        self._client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
        self._history: list[dict[str, Any]] = []
        self._tools: list[dict] | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def chat(self, user_message: str) -> tuple[str, list[dict]]:
        """
        Send a message and get a reply.

        Returns:
            (assistant_reply: str, tool_log: list[dict])
            tool_log contains each tool call with name, args, and result summary.
        """
        self._history.append({"role": "user", "content": user_message})
        tools = self._get_tools()
        tool_log: list[dict] = []

        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self._history

        for _ in range(10):  # safety limit on tool-call rounds
            response = self._client.chat.completions.create(
                model=config.OPENAI_MODEL,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
            msg = response.choices[0].message

            if msg.tool_calls:
                messages.append(msg.model_dump(exclude_unset=False))

                for tc in msg.tool_calls:
                    tool_name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}

                    log.info("Tool call: %s(%s)", tool_name, args)
                    result_str = call_tool(tool_name, args)

                    tool_log.append({
                        "tool": tool_name,
                        "args": args,
                        "result_preview": result_str[:200] + "..." if len(result_str) > 200 else result_str,
                    })

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_str,
                    })
            else:
                reply = msg.content or ""
                self._history.append({"role": "assistant", "content": reply})
                return reply, tool_log

        reply = "I reached the tool call limit. Please try a more specific question."
        self._history.append({"role": "assistant", "content": reply})
        return reply, tool_log

    def clear_history(self) -> None:
        self._history = []

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_tools(self) -> list[dict]:
        if self._tools is None:
            self._tools = list_tools()
        return self._tools
