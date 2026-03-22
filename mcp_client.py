"""
MCP client — in-process adapter
---------------------------------
Calls Jira MCP server tools directly (same Python process).
No HTTP server needed for the dashboard to work.

Provides two functions used by app.py and chatbot.py:

    list_tools()          -> list of OpenAI-compatible tool dicts
    call_tool(name, args) -> JSON string result
"""

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

# Tool registry — maps tool name -> function in jira_mcp_server
_TOOL_REGISTRY: dict[str, Any] = {}


def _load_tools() -> None:
    """Import MCP server tools into the registry (lazy, done once)."""
    if _TOOL_REGISTRY:
        return
    import jira_mcp_server as srv
    for name in [
        "get_current_sprint",
        "get_sprint_issues",
        "get_all_sprints",
        "get_team_velocity",
        "search_issues",
        "get_team_comparison",
        "generate_sprint_report",
    ]:
        fn = getattr(srv, name, None)
        if fn:
            _TOOL_REGISTRY[name] = fn


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> str:
    """
    Calls a Jira MCP tool by name with the given arguments.
    Returns the result as a JSON string.
    """
    _load_tools()
    arguments = arguments or {}
    fn = _TOOL_REGISTRY.get(name)
    if fn is None:
        return json.dumps({"error": f"Tool '{name}' not found."})
    try:
        result = fn(**arguments)
        return result if isinstance(result, str) else json.dumps(result)
    except Exception as e:
        log.error("call_tool '%s' failed: %s", name, e)
        return json.dumps({"error": str(e)})


def list_tools() -> list[dict]:
    """
    Returns the list of available tools as OpenAI tool definitions.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "get_current_sprint",
                "description": "Returns the currently active sprint details (name, id, dates, goal).",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_sprint_issues",
                "description": "Returns all issues in a sprint with Developer field, story points, status, and team label (Assignee is not used).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sprint_id": {
                            "type": "integer",
                            "description": "Sprint ID. Omit for the current active sprint.",
                        }
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_all_sprints",
                "description": "Returns a list of sprints for the board (active, closed, future).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "state": {
                            "type": "string",
                            "enum": ["active", "closed", "future", "all"],
                            "description": "Sprint state filter. Default is 'all'.",
                        }
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_team_velocity",
                "description": "Returns story points planned and completed per sprint for Josh Team and Client Team, for the last N closed sprints.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "num_sprints": {
                            "type": "integer",
                            "description": "Number of past sprints to include. Default is 6.",
                        }
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_issues",
                "description": "Run a JQL query and return matching Jira issues. Use for custom searches.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "jql": {
                            "type": "string",
                            "description": "JQL query string, e.g. 'project = ESTATE AND status = \"In Progress\"'",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Max results to return. Default 50, max 200.",
                        },
                    },
                    "required": ["jql"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_team_comparison",
                "description": "Returns a side-by-side comparison of Josh Team vs Client Team: planned points, completed points, completion %, and per-member breakdown.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sprint_id": {
                            "type": "integer",
                            "description": "Sprint ID. Omit for the current active sprint.",
                        }
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "generate_sprint_report",
                "description": "Generates a full sprint report including team comparison, per-member breakdown, completed and incomplete issues list. Use this when asked to generate or export a report.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sprint_id": {
                            "type": "integer",
                            "description": "Sprint ID. Omit for the current active sprint.",
                        }
                    },
                },
            },
        },
    ]
