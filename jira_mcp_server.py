"""
Jira MCP Server
---------------
Exposes Jira Cloud data as MCP tools callable by the AI chatbot
and directly by the Streamlit dashboard.

Run standalone (for external MCP clients like Cursor):
    python jira_mcp_server.py

The server starts a streamable-HTTP MCP server on MCP_HOST:MCP_PORT.
The Streamlit dashboard also imports this module directly for in-process calls.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from atlassian import Jira
from mcp.server.fastmcp import FastMCP

import config

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)


# ── Jira client (singleton) ──────────────────────────────────────────────────

def _get_jira() -> Jira:
    return Jira(
        url=config.JIRA_URL,
        username=config.JIRA_EMAIL,
        password=config.JIRA_API_TOKEN,
        cloud=True,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_sprints(raw: Any) -> list[dict]:
    """Handle both list and dict-with-values responses from atlassian-python-api."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return raw.get("values", [])
    return []


def _fetch_board_sprints_paginated(jira: Jira, board_id: int, state: str) -> list[dict]:
    """Fetch all sprints for a board + state (pages through the full list)."""
    page_size = int(getattr(config, "JIRA_SPRINT_PAGE_SIZE", 100) or 100)
    all_sprints: list[dict] = []
    start = 0
    while True:
        raw = jira.get_all_sprints_from_board(
            board_id, state=state, start=start, limit=page_size
        )
        batch = _extract_sprints(raw)
        all_sprints.extend(batch)
        if not batch:
            break
        start += len(batch)
        total = raw.get("total") if isinstance(raw, dict) else None
        if total is not None and start >= int(total):
            break
        if total is None and len(batch) < page_size:
            break
    return all_sprints


def _fetch_recent_closed_sprints(jira: Jira, board_id: int, tail_size: int = 50) -> list[dict]:
    """Fetch only the most recent closed sprints (tail of the list).

    Jira returns closed sprints oldest-first. We probe the total with a tiny call,
    then jump to `startAt = total - tail_size` to grab only the newest ones.
    This avoids loading all 456+ sprints.
    """
    probe = jira.get_all_sprints_from_board(board_id, state="closed", start=0, limit=1)
    total = probe.get("total") if isinstance(probe, dict) else None
    if total is None:
        return _fetch_board_sprints_paginated(jira, board_id, "closed")

    total = int(total)
    if total <= 0:
        return []

    start_at = max(0, total - tail_size)
    page_size = int(getattr(config, "JIRA_SPRINT_PAGE_SIZE", 100) or 100)
    result: list[dict] = []
    pos = start_at
    while pos < total:
        raw = jira.get_all_sprints_from_board(board_id, state="closed", start=pos, limit=page_size)
        batch = _extract_sprints(raw)
        result.extend(batch)
        if not batch:
            break
        pos += len(batch)
    log.info("Closed sprints: total=%d, fetched last %d (startAt=%d)", total, len(result), start_at)
    return result


def _jira_iso_ts(value: Any) -> float | None:
    """Parse Jira Agile sprint date strings to UTC epoch seconds. Returns None if missing/invalid."""
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _closed_sprint_has_parseable_date(sp: dict) -> bool:
    """True if we have at least one ISO date for time-based sort / month filter."""
    for key in ("completeDate", "endDate", "startDate"):
        if _jira_iso_ts(sp.get(key)) is not None:
            return True
    return False


def _closed_sprint_recency_ts(sp: dict) -> float:
    """Best timestamp for 'how recent' a closed sprint is (newer = larger).

    Sprint numeric **id** is NOT a Unix timestamp — never use it for calendar cutoffs.
    For sprints with no dates, we sort by id descending only relative to each other.
    """
    for key in ("completeDate", "endDate", "startDate"):
        ts = _jira_iso_ts(sp.get(key))
        if ts is not None:
            return ts
    try:
        return float(sp.get("id") or 0)
    except (TypeError, ValueError):
        return 0.0


def _closed_sprint_sort_key(sp: dict) -> tuple[int, float]:
    """Sort closed: dated sprints by real time (newest first); undated by id only."""
    for key in ("completeDate", "endDate", "startDate"):
        ts = _jira_iso_ts(sp.get(key))
        if ts is not None:
            return (1, ts)
    try:
        return (0, float(sp.get("id") or 0))
    except (TypeError, ValueError):
        return (0, 0.0)


def _future_sprint_start_ts(sp: dict) -> float:
    """Soonest start first; undated futures sort last."""
    for key in ("startDate", "endDate"):
        ts = _jira_iso_ts(sp.get(key))
        if ts is not None:
            return ts
    return float("inf")


_CRM_2_SPRINT_NAME_RE = re.compile(r"^CRM_2\.(\d+)\s*$", re.IGNORECASE)


def _sprint_name_passes_crm_2_patch(name: Any) -> bool:
    """Require CRM_2.<patch> with patch in [min, max] when those config values are set."""
    min_raw = getattr(config, "DASHBOARD_SPRINT_MIN_CRM_2_PATCH", None)
    max_raw = getattr(config, "DASHBOARD_SPRINT_MAX_CRM_2_PATCH", None)
    if min_raw is None and max_raw is None:
        return True
    if not name or not isinstance(name, str):
        return False
    m = _CRM_2_SPRINT_NAME_RE.match(name.strip())
    if not m:
        return False
    try:
        patch = int(m.group(1))
    except ValueError:
        return False
    if min_raw is not None:
        try:
            if patch < int(min_raw):
                return False
        except (TypeError, ValueError):
            return True
    if max_raw is not None:
        try:
            if patch > int(max_raw):
                return False
        except (TypeError, ValueError):
            pass
    return True


def _filter_sprints_by_crm_2_name(sprints: list[dict]) -> list[dict]:
    if (
        getattr(config, "DASHBOARD_SPRINT_MIN_CRM_2_PATCH", None) is None
        and getattr(config, "DASHBOARD_SPRINT_MAX_CRM_2_PATCH", None) is None
    ):
        return sprints
    return [sp for sp in sprints if _sprint_name_passes_crm_2_patch(sp.get("name"))]


def _sprint_unified_sort_key(row: dict) -> tuple[int, float]:
    """Most recently active first: closed uses completion dates; active/future use start → end → complete."""
    state = (row.get("state") or "").lower()
    if state == "closed":
        return _closed_sprint_sort_key(row)
    for key in ("startDate", "endDate", "completeDate"):
        ts = _jira_iso_ts(row.get(key))
        if ts is not None:
            return (1, ts)
    # Undated active/future still matter for the selector — rank as "now" so they are not buried.
    if state in ("active", "future"):
        return (1, datetime.now(timezone.utc).timestamp())
    try:
        return (0, float(row.get("id") or 0))
    except (TypeError, ValueError):
        return (0, 0.0)


def _merge_sort_cap_sprints(rows: list[dict]) -> list[dict]:
    """Single list, newest-by-activity first, then cap (DASHBOARD_CLOSED_SPRINT_LIMIT)."""
    merged = list(rows)
    merged.sort(key=_sprint_unified_sort_key, reverse=True)
    cap = getattr(config, "DASHBOARD_CLOSED_SPRINT_LIMIT", 10)
    if cap is not None:
        merged = merged[: int(cap)]
    return merged


def _story_points(issue: dict) -> float:
    """Extract story points — checks all known custom field names for this Jira instance."""
    fields = issue.get("fields", {})
    # customfield_10024 is the story points field for selldo.atlassian.net
    for key in ("customfield_10024", "story_points", "storyPoints",
                "customfield_10016", "customfield_10028", "customfield_10004"):
        val = fields.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return 0.0


def _issue_fixversion_names(issue: dict) -> set[str]:
    """Normalize issue fixVersions to a lowercase name set."""
    fvs = issue.get("fields", {}).get("fixVersions") or []
    names: set[str] = set()
    for fv in fvs:
        name = (fv or {}).get("name")
        if name and str(name).strip():
            names.add(str(name).strip().lower())
    return names


def _developer_name(issue: dict) -> str:
    """
    Returns the Developer name from customfield_10084 (the 'Developer' field) only.
    Does not use Assignee. If multiple developers, joins with ' / '. If unset: Unassigned.
    """
    devs = issue.get("fields", {}).get("customfield_10084") or []
    if devs:
        names = [d.get("displayName", "") for d in devs if d.get("displayName")]
        if names:
            return " / ".join(names)
    return "Unassigned"


def _team_of(display_name: str) -> str:
    """Match team by display name (case-insensitive)."""
    name_lower = display_name.lower()
    if name_lower in [m.lower() for m in config.JOSH_TEAM_MEMBERS]:
        return "Josh Team"
    if name_lower in [m.lower() for m in config.CLIENT_TEAM_MEMBERS]:
        return "Client Team"
    return "Other"


def _is_done(issue: dict) -> bool:
    category = (
        issue.get("fields", {})
        .get("status", {})
        .get("statusCategory", {})
        .get("key", "")
    )
    return category == "done"


def _is_wont_fix(issue: dict) -> bool:
    """
    Detect "Won't Fix" issues for coverage reporting.

    Jira teams sometimes represent Won't Fix as either a terminal Status or a Resolution.
    We treat either as covered for the FixVersion coverage metric.
    """
    fields = issue.get("fields", {}) or {}
    status_name = str((fields.get("status") or {}).get("name", "")).strip().lower()
    resolution_name = str((fields.get("resolution") or {}).get("name", "")).strip().lower()
    return status_name in {"won't fix", "wont fix"} or resolution_name in {"won't fix", "wont fix"}


def _jql_all(jira: Jira, jql: str, fields: list[str], page_size: int = 100) -> list[dict]:
    """Fetch ALL issues matching a JQL query, handling Jira Cloud's 100-per-page cap."""
    all_issues: list[dict] = []

    # Jira Cloud search/jql may omit `total`; use nextPageToken pagination.
    if getattr(jira, "cloud", False):
        token = None
        while True:
            if token:
                page = jira.enhanced_jql(
                    jql=jql,
                    fields=fields,
                    nextPageToken=token,
                    limit=page_size,
                )
            else:
                page = jira.enhanced_jql(
                    jql=jql,
                    fields=fields,
                    limit=page_size,
                )
            batch = page.get("issues", [])
            all_issues.extend(batch)
            token = page.get("nextPageToken")
            if not batch or not token:
                break
        return all_issues

    # Server/DC fallback with start/total pagination.
    start = 0
    while True:
        page = jira.jql(jql, limit=page_size, start=start, fields=fields)
        batch = page.get("issues", [])
        all_issues.extend(batch)
        total = page.get("total")
        start += len(batch)
        if not batch:
            break
        if total is not None and start >= int(total):
            break
        if total is None and len(batch) < page_size:
            break
    return all_issues


# ── MCP App ──────────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="sprinttrace",
    instructions=(
        "You are SprintTrace's Jira reporting assistant. Use the available tools to fetch "
        "sprint data, compare teams, and generate reports. Always prefer tool "
        "calls over guessing. When asked for a report, call generate_sprint_report."
    ),
)


# ── Tool: get_current_sprint ─────────────────────────────────────────────────

@mcp.tool()
def get_current_sprint() -> str:
    """Returns the currently active sprint for the configured Jira board.
    Includes sprint id, name, start date, end date, and goal."""
    jira = _get_jira()
    try:
        raw = jira.get_all_sprints_from_board(config.JIRA_BOARD_ID, state="active")
        sprints = _filter_sprints_by_crm_2_name(_extract_sprints(raw))
        if not sprints:
            return json.dumps({"error": "No active sprint found."})
        sprint = sprints[0]
        return json.dumps({
            "id": sprint.get("id"),
            "name": sprint.get("name"),
            "state": sprint.get("state"),
            "startDate": sprint.get("startDate"),
            "endDate": sprint.get("endDate"),
            "goal": sprint.get("goal", ""),
        })
    except Exception as e:
        log.error("get_current_sprint failed: %s", e)
        return json.dumps({"error": str(e)})


# ── Tool: get_sprint_issues ──────────────────────────────────────────────────

@mcp.tool()
def get_sprint_issues(sprint_id: int | None = None) -> str:
    """Returns all issues in a sprint with Developer, story points, status, and team.
    If sprint_id is omitted, uses the current active sprint.

    Args:
        sprint_id: Jira sprint ID (integer). Pass null to use active sprint.
    """
    jira = _get_jira()
    try:
        if sprint_id is None:
            raw = jira.get_all_sprints_from_board(config.JIRA_BOARD_ID, state="active")
            sprints = _filter_sprints_by_crm_2_name(_extract_sprints(raw))
            if not sprints:
                return json.dumps({"error": "No active sprint found."})
            sprint_id = sprints[0]["id"]
            sprint_name = sprints[0]["name"]
        else:
            sprint_name = f"Sprint {sprint_id}"

        jql = f"sprint = {sprint_id} ORDER BY created"
        _fields = [
            "summary", "status",
            "customfield_10084",  # Developer
            "customfield_10024", "customfield_10016", "customfield_10028", "customfield_10004",
            "issuetype", "priority",
        ]
        issues = _jql_all(jira, jql, _fields)

        result = []
        for issue in issues:
            dev_name = _developer_name(issue)
            result.append({
                "key": issue.get("key"),
                "summary": issue.get("fields", {}).get("summary", ""),
                "status": issue.get("fields", {}).get("status", {}).get("name", ""),
                "statusCategory": (
                    issue.get("fields", {})
                    .get("status", {})
                    .get("statusCategory", {})
                    .get("key", "")
                ),
                "developerName": dev_name,
                "team": _team_of(dev_name),
                "storyPoints": _story_points(issue),
                "done": _is_done(issue),
                "issueType": issue.get("fields", {}).get("issuetype", {}).get("name", ""),
            })

        return json.dumps({
            "sprintId": sprint_id,
            "sprintName": sprint_name,
            "issues": result,
        })
    except Exception as e:
        log.error("get_sprint_issues failed: %s", e)
        return json.dumps({"error": str(e)})


# ── Tool: get_all_sprints ────────────────────────────────────────────────────

@mcp.tool()
def get_all_sprints(state: str = "all") -> str:
    """Returns sprints for the configured board.

    Simple approach:
      1. Fetch active + future normally (tiny — usually 1-2 sprints each).
      2. For closed: probe the total, then fetch only the LAST ~50
         (Jira returns oldest-first, so tail = newest).
      3. Filter by CRM_2.<patch> name rules.
      4. Merge all, sort by recency, keep top DASHBOARD_CLOSED_SPRINT_LIMIT.

    Args:
        state: "active", "closed", "future", or "all" (default).
    """
    jira = _get_jira()
    try:
        sprints: list[dict] = []

        if state in ("all", "active"):
            sprints.extend(_fetch_board_sprints_paginated(jira, config.JIRA_BOARD_ID, "active"))
        if state in ("all", "future"):
            sprints.extend(_fetch_board_sprints_paginated(jira, config.JIRA_BOARD_ID, "future"))
        if state in ("all", "closed"):
            tail = int(getattr(config, "JIRA_CLOSED_SPRINT_TAIL_SIZE", 50) or 50)
            sprints.extend(_fetch_recent_closed_sprints(jira, config.JIRA_BOARD_ID, tail_size=tail))

        sprints = _filter_sprints_by_crm_2_name(sprints)

        result = [
            {
                "id": sp.get("id"),
                "name": sp.get("name"),
                "state": sp.get("state"),
                "startDate": sp.get("startDate"),
                "endDate": sp.get("endDate"),
                "completeDate": sp.get("completeDate"),
            }
            for sp in sprints
        ]

        combined = _merge_sort_cap_sprints(result)
        return json.dumps(combined)
    except Exception as e:
        log.error("get_all_sprints failed: %s", e)
        return json.dumps({"error": str(e)})


# ── Tool: get_team_velocity ──────────────────────────────────────────────────

@mcp.tool()
def get_team_velocity(num_sprints: int = 6) -> str:
    """Returns story points completed per sprint for both teams (last N closed sprints).

    Fetches only the tail of closed sprints from Jira (newest), filters by CRM name,
    sorts by recency, and takes num_sprints.

    Args:
        num_sprints: Number of past sprints to include (default 6).
    """
    jira = _get_jira()
    try:
        tail = int(getattr(config, "JIRA_CLOSED_SPRINT_TAIL_SIZE", 50) or 50)
        closed = _fetch_recent_closed_sprints(jira, config.JIRA_BOARD_ID, tail_size=tail)
        closed = _filter_sprints_by_crm_2_name(closed)
        closed.sort(key=_closed_sprint_sort_key, reverse=True)
        recent = closed[:num_sprints]

        velocity: list[dict] = []
        _vel_fields = [
            "status",
            "customfield_10084",  # Developer
            "customfield_10024", "customfield_10016", "customfield_10028", "customfield_10004",
        ]
        for sprint in reversed(recent):
            sid = sprint["id"]
            jql = f"sprint = {sid}"
            issues = _jql_all(jira, jql, _vel_fields)

            josh_planned = josh_done = client_planned = client_done = 0.0
            for issue in issues:
                team = _team_of(_developer_name(issue))
                pts = _story_points(issue)
                done = _is_done(issue)
                if team == "Josh Team":
                    josh_planned += pts
                    if done:
                        josh_done += pts
                elif team == "Client Team":
                    client_planned += pts
                    if done:
                        client_done += pts

            velocity.append({
                "sprintId": sid,
                "sprintName": sprint.get("name"),
                "endDate": sprint.get("endDate"),
                "joshPlanned": josh_planned,
                "joshCompleted": josh_done,
                "clientPlanned": client_planned,
                "clientCompleted": client_done,
            })

        return json.dumps(velocity)
    except Exception as e:
        log.error("get_team_velocity failed: %s", e)
        return json.dumps({"error": str(e)})


# ── Tool: search_issues ──────────────────────────────────────────────────────

@mcp.tool()
def search_issues(jql: str, max_results: int = 50) -> str:
    """Jira **issue** search via JQL (Jira Cloud: GET .../rest/api/3/search/jql).

    This does **not** return sprint rows. To list sprints for the board, use get_all_sprints.
    Use JQL to find issues in sprints, e.g. `project = KEY AND sprint in closedSprints()`
    or `sprint = 12345`. Each issue includes a `sprint` field (ids/names/dates when present).

    Each issue includes developerName (Developer custom field only; Assignee is not used).

    Args:
        jql: JQL query string, e.g. 'project = PROJ AND status = "In Progress"'
        max_results: Maximum number of results to return (default 50, max 200).
    """
    jira = _get_jira()
    try:
        max_results = min(max(1, int(max_results)), 200)
        raw = jira.jql(jql, limit=max_results, fields=[
            "summary", "status", "sprint",
            "customfield_10084",  # Developer
            "customfield_10024", "customfield_10016", "customfield_10028", "customfield_10004",
            "issuetype", "priority", "created", "updated",
        ])
        issues = raw.get("issues", [])
        result = []
        for issue in issues:
            dev_name = _developer_name(issue)
            result.append({
                "key": issue.get("key"),
                "summary": issue.get("fields", {}).get("summary", ""),
                "status": issue.get("fields", {}).get("status", {}).get("name", ""),
                "sprint": issue.get("fields", {}).get("sprint"),
                "developerName": dev_name,
                "team": _team_of(dev_name),
                "storyPoints": _story_points(issue),
                "done": _is_done(issue),
                "issueType": issue.get("fields", {}).get("issuetype", {}).get("name", ""),
                "priority": issue.get("fields", {}).get("priority", {}).get("name", ""),
            })
        return json.dumps({"total": raw.get("total", len(result)), "issues": result})
    except Exception as e:
        log.error("search_issues failed: %s", e)
        return json.dumps({"error": str(e)})


# ── Tool: get_fixversion_coverage ────────────────────────────────────────────

@mcp.tool()
def get_fixversion_coverage(fix_versions: list[str], project_key: str | None = None) -> str:
    """Return story-point coverage for one or more FixVersions.

    Coverage = completed points / planned points (done status category).
    """
    jira = _get_jira()
    try:
        versions = [str(v).strip() for v in (fix_versions or []) if str(v).strip()]
        if not versions:
            return json.dumps({
                "projectKey": project_key or config.JIRA_PROJECT_KEY,
                "fixVersions": [],
                "planned": 0.0,
                "completed": 0.0,
                "coveragePct": 0.0,
                "issues": 0,
                "perTeam": {
                    "Josh Team": {"planned": 0.0, "completed": 0.0, "coveragePct": 0.0, "issues": 0},
                    "Client Team": {"planned": 0.0, "completed": 0.0, "coveragePct": 0.0, "issues": 0},
                },
            })

        unique_versions = sorted(set(versions))
        proj = (project_key or config.JIRA_PROJECT_KEY or "").strip()
        safe_versions = [v.replace('"', '\\"') for v in unique_versions]
        jql_versions = ", ".join(f'"{v}"' for v in safe_versions)
        if proj:
            jql = f'project = "{proj}" AND fixVersion in ({jql_versions})'
        else:
            jql = f"fixVersion in ({jql_versions})"

        _fields = [
            "status",
            "resolution",
            "customfield_10084",  # Developer
            "customfield_10024", "customfield_10016", "customfield_10028", "customfield_10004",
            "fixVersions",
        ]
        issues = _jql_all(jira, jql, _fields)
        selected_fv = {v.lower() for v in unique_versions}

        planned = 0.0
        completed = 0.0
        per_dev: dict[str, dict[str, float | int]] = {}
        per_team: dict[str, dict[str, float | int]] = {
            "Josh Team": {"planned": 0.0, "completed": 0.0, "issues": 0},
            "Client Team": {"planned": 0.0, "completed": 0.0, "issues": 0},
        }
        matched_issue_count = 0
        for issue in issues:
            # Strict release match: include only issues tagged with selected FixVersion(s).
            issue_fv = _issue_fixversion_names(issue)
            if not (issue_fv & selected_fv):
                continue
            matched_issue_count += 1
            pts = _story_points(issue)
            done = _is_done(issue)
            covered = done or _is_wont_fix(issue)
            planned += pts
            if covered:
                completed += pts

            dev = _developer_name(issue)
            d = per_dev.setdefault(dev, {"planned": 0.0, "completed": 0.0, "issues": 0})
            d["planned"] = float(d["planned"]) + pts
            if covered:
                d["completed"] = float(d["completed"]) + pts
            d["issues"] = int(d["issues"]) + 1

            team = _team_of(dev)
            if team in per_team:
                t = per_team[team]
                t["planned"] = float(t["planned"]) + pts
                if covered:
                    t["completed"] = float(t["completed"]) + pts
                t["issues"] = int(t["issues"]) + 1

        pct = round((completed / planned * 100.0) if planned else 0.0, 1)
        for t in per_team.values():
            tp = float(t["planned"])
            tc = float(t["completed"])
            t["coveragePct"] = round((tc / tp * 100.0) if tp else 0.0, 1)
        return json.dumps({
            "projectKey": proj,
            "fixVersions": unique_versions,
            "planned": planned,
            "completed": completed,
            "coveragePct": pct,
            "issues": matched_issue_count,
            "perTeam": per_team,
            "perDeveloper": per_dev,
        })
    except Exception as e:
        log.error("get_fixversion_coverage failed: %s", e)
        return json.dumps({"error": str(e)})


# ── Tool: get_fixversion_issues ───────────────────────────────────────────────

@mcp.tool()
def get_fixversion_issues(fix_versions: list[str], project_key: str | None = None) -> str:
    """Return issue-level data for one or more FixVersions (same shape as sprint issues rows)."""
    jira = _get_jira()
    try:
        versions = [str(v).strip() for v in (fix_versions or []) if str(v).strip()]
        if not versions:
            return json.dumps({"fixVersions": [], "issues": []})

        unique_versions = sorted(set(versions))
        proj = (project_key or config.JIRA_PROJECT_KEY or "").strip()
        safe_versions = [v.replace('"', '\\"') for v in unique_versions]
        jql_versions = ", ".join(f'"{v}"' for v in safe_versions)
        if proj:
            jql = f'project = "{proj}" AND fixVersion in ({jql_versions}) ORDER BY created'
        else:
            jql = f"fixVersion in ({jql_versions}) ORDER BY created"

        _fields = [
            "summary", "status",
            "customfield_10084",  # Developer
            "customfield_10024", "customfield_10016", "customfield_10028", "customfield_10004",
            "issuetype", "priority", "fixVersions",
        ]
        issues = _jql_all(jira, jql, _fields)
        selected_fv = {v.lower() for v in unique_versions}

        result: list[dict] = []
        for issue in issues:
            issue_fv = _issue_fixversion_names(issue)
            if not (issue_fv & selected_fv):
                continue
            dev_name = _developer_name(issue)
            result.append({
                "key": issue.get("key"),
                "summary": issue.get("fields", {}).get("summary", ""),
                "status": issue.get("fields", {}).get("status", {}).get("name", ""),
                "statusCategory": (
                    issue.get("fields", {})
                    .get("status", {})
                    .get("statusCategory", {})
                    .get("key", "")
                ),
                "developerName": dev_name,
                "team": _team_of(dev_name),
                "storyPoints": _story_points(issue),
                "done": _is_done(issue),
                "issueType": issue.get("fields", {}).get("issuetype", {}).get("name", ""),
                "matchedFixVersions": sorted(issue_fv & selected_fv),
            })
        return json.dumps({"fixVersions": unique_versions, "issues": result})
    except Exception as e:
        log.error("get_fixversion_issues failed: %s", e)
        return json.dumps({"error": str(e)})


# ── Tool: get_team_comparison ────────────────────────────────────────────────

@mcp.tool()
def get_team_comparison(sprint_id: int | None = None) -> str:
    """Returns a side-by-side comparison of Josh Team vs Client Team for a sprint.
    Includes planned points, completed points, completion %, and per-member breakdown.

    Args:
        sprint_id: Jira sprint ID. Pass null to use the current active sprint.
    """
    data = json.loads(get_sprint_issues(sprint_id=sprint_id))
    if "error" in data:
        return json.dumps(data)

    issues = data["issues"]
    teams: dict[str, dict[str, Any]] = {
        "Josh Team":   {"planned": 0.0, "completed": 0.0, "members": {}},
        "Client Team": {"planned": 0.0, "completed": 0.0, "members": {}},
        "Other":       {"planned": 0.0, "completed": 0.0, "members": {}},
    }

    for issue in issues:
        team = issue["team"]
        pts = issue["storyPoints"]
        dev_name = issue.get("developerName") or "Unassigned"
        done = issue["done"]

        t = teams[team]
        t["planned"] += pts
        if done:
            t["completed"] += pts

        member = t["members"].setdefault(
            dev_name, {"planned": 0.0, "completed": 0.0, "issues": 0}
        )
        member["planned"] += pts
        member["issues"] += 1
        if done:
            member["completed"] += pts

    summary: dict[str, Any] = {}
    for team_name, t in teams.items():
        planned = t["planned"]
        completed = t["completed"]
        pct = round((completed / planned * 100) if planned else 0, 1)
        summary[team_name] = {
            "planned": planned,
            "completed": completed,
            "completionPct": pct,
            "members": t["members"],
        }

    return json.dumps({
        "sprintId": data["sprintId"],
        "sprintName": data["sprintName"],
        "comparison": summary,
    })


# ── Tool: generate_sprint_report ─────────────────────────────────────────────

@mcp.tool()
def generate_sprint_report(sprint_id: int | None = None) -> str:
    """Generates a full structured sprint report including team comparison,
    per-member breakdown, incomplete issues, and a summary narrative.
    Use this when asked to generate or export a report.

    Args:
        sprint_id: Jira sprint ID. Pass null to use the current active sprint.
    """
    comparison_raw = json.loads(get_team_comparison(sprint_id=sprint_id))
    if "error" in comparison_raw:
        return json.dumps(comparison_raw)

    issues_raw = json.loads(get_sprint_issues(sprint_id=sprint_id))
    if "error" in issues_raw:
        return json.dumps(issues_raw)

    issues = issues_raw["issues"]
    incomplete = [i for i in issues if not i["done"] and i["storyPoints"] > 0]
    complete = [i for i in issues if i["done"]]

    comp = comparison_raw["comparison"]
    josh = comp.get("Josh Team", {})
    client = comp.get("Client Team", {})

    narrative_lines = [
        f"Sprint: {comparison_raw['sprintName']}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "Josh Team:",
        f"  Planned: {josh.get('planned', 0)} pts | "
        f"Completed: {josh.get('completed', 0)} pts | "
        f"{josh.get('completionPct', 0)}% done",
        "",
        "Client Team:",
        f"  Planned: {client.get('planned', 0)} pts | "
        f"Completed: {client.get('completed', 0)} pts | "
        f"{client.get('completionPct', 0)}% done",
        "",
        f"Total issues: {len(issues)} | Completed: {len(complete)} | Incomplete: {len(incomplete)}",
    ]

    return json.dumps({
        "sprintId": comparison_raw["sprintId"],
        "sprintName": comparison_raw["sprintName"],
        "generatedAt": datetime.now().isoformat(),
        "summary": "\n".join(narrative_lines),
        "comparison": comp,
        "incompleteIssues": incomplete,
        "completedIssues": complete,
    })


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("Starting Jira MCP server on %s:%s", config.MCP_HOST, config.MCP_PORT)
    mcp.run(
        transport="streamable-http",
        host=config.MCP_HOST,
        port=config.MCP_PORT,
    )
