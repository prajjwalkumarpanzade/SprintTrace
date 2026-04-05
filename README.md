# SprintTrace

Executive-friendly sprint reporting: a Streamlit app that connects to **Jira Cloud**
via an MCP server, compares **Josh Team** vs **Client Team** story points and workflow
stages, and includes an AI assistant (GPT-4o) for live Q&A and report generation.

---

## Quick Start

### 1. Install dependencies

```powershell
cd "SprintTrace"   # or your project folder name
.\venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure credentials

Copy `.env.example` to `.env` and fill in your values:

```powershell
copy .env.example .env
```

Edit `.env`:
```
JIRA_URL=https://yourcompany.atlassian.net
JIRA_EMAIL=you@yourcompany.com
JIRA_API_TOKEN=your_token_here
JIRA_BOARD_ID=1
JIRA_PROJECT_KEY=PROJ
OPENAI_API_KEY=sk-...
```

> Get your Jira API token from:
> https://id.atlassian.com/manage-profile/security/api-tokens

### 3. Configure team members

Edit `config.py` and add team member Jira emails:

```python
JOSH_TEAM_MEMBERS = [
    "alice@jostech.com",
    "bob@jostech.com",
]

CLIENT_TEAM_MEMBERS = [
    "john@client.com",
    "jane@client.com",
]
```

**Sprint list (dashboard):** Active + future are fetched normally. Closed sprints are fetched from the **tail** of Jira’s closed list (`JIRA_CLOSED_SPRINT_TAIL_SIZE`, default 50), then merged and sorted by recency. The selector shows the top **`DASHBOARD_CLOSED_SPRINT_LIMIT`** (default 10) after filtering.

**Sprint names:** **`DASHBOARD_SPRINT_MIN_CRM_2_PATCH`** (default **60**) and optional **`DASHBOARD_SPRINT_MAX_CRM_2_PATCH`** (default **`None`**) restrict the numeric part (e.g. min **60** → **`CRM_2.60`** onward including **`CRM_2.70`**; max **69** → only **`CRM_2.60`–`CRM_2.69`**). Set both min/max to **`None`** to disable the name filter.

**Release month view (CSV):** Add `release_calendar.csv` (see sample file in repo) with at least `Deployment` and `FixVersion` columns. Sidebar month filter uses Deployment month and computes month-level story-point coverage across all FixVersions in that month.

**Issue search:** The **`search_issues`** tool uses Jira **JQL** (`/rest/api/3/search/jql` on Cloud). It returns **issues**, not sprint metadata. To reason about sprints via JQL, use clauses like `sprint in closedSprints()` or `sprint = 12345` and inspect each issue’s `sprint` field in the result.

### 4. Launch

**Option A — One command (starts both MCP server + dashboard):**
```powershell
.\start.ps1
```

**Option B — Manually in two terminals:**

Terminal 1 (MCP Server):
```powershell
.\venv\Scripts\activate
python jira_mcp_server.py
```

Terminal 2 (Dashboard):
```powershell
.\venv\Scripts\activate
streamlit run app.py
```

Then open http://localhost:8501 in your browser.

---

## Project Structure

```
SprintTrace/
├── app.py               # Streamlit dashboard (main UI)
├── jira_mcp_server.py   # MCP server — exposes Jira as AI tools
├── mcp_client.py        # MCP client used by dashboard + chatbot
├── chatbot.py           # OpenAI GPT-4o chatbot with tool-calls loop
├── config.py            # Team config, board ID, project key
├── requirements.txt
├── start.ps1            # Convenience launcher (Windows)
├── .env.example         # Environment variable template
└── .env                 # Your secrets (DO NOT commit this)
```

---

## MCP Tools Available

| Tool | Description |
|------|-------------|
| `get_current_sprint` | Active sprint details |
| `get_sprint_issues` | All issues with Developer field + story points (Assignee not used) |
| `get_all_sprints` | List of all sprints (active/closed/future) |
| `get_team_velocity` | Completed points per sprint (last N sprints) |
| `search_issues` | JQL issue search (not a sprint list API; see README above) |
| `get_team_comparison` | Josh vs Client side-by-side stats |
| `generate_sprint_report` | Full report for export |

---

## Dashboard Features

- **Sprint selector** — switch between any sprint
- **Team comparison bar chart** — Planned vs Completed for both teams
- **Completion gauges** — % done per team
- **Per-member tables** — individual planned/completed/remaining
- **Velocity trend** — line chart across last N sprints
- **Export** — Download Excel report or CSV of all issues
- **Sprint Issues** — status filter is case-insensitive; `STATUS_FILTER_SYNONYMS` in `config.py` maps labels like “Under Review” to your real Jira statuses (e.g. `PR Review`)

## AI Chatbot Features

- Live tool calls — fetches fresh Jira data per question
- Quick action buttons for common queries
- Export sprint report from chat
- Example questions:
  - "How many points did Josh team complete last sprint?"
  - "Who has the most incomplete tickets?"
  - "Compare our velocity to client team over last 3 sprints"
  - "Generate a sprint report and export it"

---

## Finding Your Jira Board ID

1. Open your Jira board in the browser
2. Look at the URL: `https://yourcompany.atlassian.net/jira/software/projects/PROJ/boards/42`
3. The number at the end (`42`) is your Board ID — put it in `.env` as `JIRA_BOARD_ID`
