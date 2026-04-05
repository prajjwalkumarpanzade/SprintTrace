"""
SprintTrace — executive sprint reporting (Streamlit)
---------------------------------------
Run with:
    streamlit run app.py
"""

import html as html_module
import importlib
import io
import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Reload config + server modules every run so edits to config.py take effect
# immediately without needing to restart the Streamlit server.
import config
importlib.reload(config)

import jira_mcp_server
importlib.reload(jira_mcp_server)

import mcp_client
importlib.reload(mcp_client)

from mcp_client import call_tool

logging.basicConfig(level=logging.INFO)

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="SprintTrace",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Hide Plotly modebar (zoom, pan, download, reset axes, etc.) on all charts.
PLOTLY_CHART_CONFIG: dict = {
    "displayModeBar": False,
}

# ── Custom CSS ────────────────────────────────────────────────────────────────

st.markdown("""
<style>
    .metric-card {
        background: #1e2130;
        border-radius: 10px;
        padding: 18px 22px;
        margin-bottom: 10px;
    }
    .metric-label { color: #8b95b0; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; }
    .metric-value { color: #ffffff; font-size: 32px; font-weight: 700; }
    .metric-sub   { color: #52d48e; font-size: 13px; }
    .team-josh   { color: #4f8ef7; font-weight: 700; }
    .team-client { color: #f7a24f; font-weight: 700; }
    .tool-badge { background: #0e4d2e; color: #52d48e; border-radius: 4px;
                  padding: 2px 8px; font-size: 11px; margin-right: 4px; }

    /* ── AI Assistant: Claude-like chat ── */
    [data-testid="stChatMessage"] {
        border-radius: 16px !important;
        padding: 14px 18px !important;
        margin-bottom: 6px !important;
        border: none !important;
        max-width: 92%;
    }
    /* User bubble — right-aligned, accent background */
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
        background: linear-gradient(135deg, #2d3a5c 0%, #263052 100%) !important;
        margin-left: auto !important;
        border: 1px solid rgba(79, 142, 247, 0.18) !important;
    }
    /* Assistant bubble — left-aligned, subtle background */
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
        background: #1a1d2e !important;
        margin-right: auto !important;
        border: 1px solid rgba(255,255,255,0.06) !important;
    }
    /* Chat input bar styling */
    [data-testid="stChatInput"] {
        border-radius: 24px !important;
        border: 1px solid rgba(255,255,255,0.12) !important;
        background: #1a1d2e !important;
        transition: border-color 0.2s;
    }
    [data-testid="stChatInput"]:focus-within {
        border-color: rgba(79, 142, 247, 0.5) !important;
        box-shadow: 0 0 0 2px rgba(79, 142, 247, 0.12) !important;
    }
    [data-testid="stChatInput"] textarea {
        color: #e8eaf2 !important;
    }
    [data-testid="stChatInput"] textarea::placeholder {
        color: #6b7288 !important;
    }
    /* Quick-action buttons row */
    .quick-action-btn button {
        border-radius: 20px !important;
        font-size: 13px !important;
        padding: 6px 14px !important;
        border: 1px solid rgba(255,255,255,0.10) !important;
        background: rgba(255,255,255,0.04) !important;
        transition: all 0.15s;
    }
    .quick-action-btn button:hover {
        background: rgba(79, 142, 247, 0.12) !important;
        border-color: rgba(79, 142, 247, 0.3) !important;
    }

    /* Developer comparison tables */
    .dev-table-card {
        border-radius: 14px;
        overflow: hidden;
        border: 1px solid rgba(255,255,255,0.08);
        background: linear-gradient(165deg, #1a1d2e 0%, #141622 100%);
        box-shadow: 0 8px 32px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.04);
        margin-top: 6px;
        display: flex;
        flex-direction: column;
        min-height: 0;
    }
    /* Scroll body: vertical + horizontal; header strip stays fixed above */
    .dev-table-card__scroll {
        max-height: min(52vh, 420px);
        overflow-y: auto;
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        scrollbar-gutter: stable;
        flex: 1 1 auto;
        min-height: 0;
        scrollbar-width: thin;
        scrollbar-color: rgba(255,255,255,0.25) rgba(0,0,0,0.25);
    }
    .dev-table-card__scroll::-webkit-scrollbar {
        width: 9px;
        height: 9px;
    }
    .dev-table-card__scroll::-webkit-scrollbar-track {
        background: rgba(0,0,0,0.2);
        border-radius: 6px;
    }
    .dev-table-card__scroll::-webkit-scrollbar-thumb {
        background: rgba(255,255,255,0.18);
        border-radius: 6px;
        border: 2px solid transparent;
        background-clip: padding-box;
    }
    .dev-table-card__scroll::-webkit-scrollbar-thumb:hover {
        background: rgba(255,255,255,0.28);
        background-clip: padding-box;
    }
    .dev-table-card--josh {
        border-color: rgba(79, 142, 247, 0.35);
        box-shadow: 0 8px 32px rgba(0,0,0,0.35), 0 0 0 1px rgba(79, 142, 247, 0.12) inset;
    }
    .dev-table-card--client {
        border-color: rgba(247, 162, 79, 0.35);
        box-shadow: 0 8px 32px rgba(0,0,0,0.35), 0 0 0 1px rgba(247, 162, 79, 0.12) inset;
    }
    .dev-table-card__head {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 12px 16px;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #8b95b0;
        border-bottom: 1px solid rgba(255,255,255,0.06);
        background: rgba(0,0,0,0.2);
        flex-shrink: 0;
    }
    .dev-table-card--josh .dev-table-card__accent {
        width: 4px; height: 14px; border-radius: 2px; background: #4f8ef7;
        box-shadow: 0 0 12px rgba(79, 142, 247, 0.5);
    }
    .dev-table-card--client .dev-table-card__accent {
        width: 4px; height: 14px; border-radius: 2px; background: #f7a24f;
        box-shadow: 0 0 12px rgba(247, 162, 79, 0.45);
    }
    table.dev-table {
        width: 100%;
        min-width: 640px;
        border-collapse: collapse;
        font-size: 14px;
        font-feature-settings: "tnum" 1;
    }
    table.dev-table thead th {
        text-align: left;
        padding: 10px 14px;
        color: #a8b0c8;
        font-weight: 600;
        font-size: 11px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        border-bottom: 1px solid rgba(255,255,255,0.08);
        background: #1c2030;
        position: sticky;
        top: 0;
        z-index: 3;
        box-shadow: 0 1px 0 rgba(255,255,255,0.06);
    }
    table.dev-table thead th.num {
        text-align: right;
    }
    table.dev-table tbody td {
        padding: 10px 14px;
        color: #e8eaf2;
        border-bottom: 1px solid rgba(255,255,255,0.04);
        vertical-align: middle;
    }
    table.dev-table tbody td.num {
        text-align: right;
        font-variant-numeric: tabular-nums;
        font-weight: 600;
        color: #c5cad8;
    }
    table.dev-table tbody td.dev-name {
        font-weight: 600;
        color: #f0f2f8;
        min-width: 7.5rem;
        max-width: 11rem;
        word-wrap: break-word;
        overflow-wrap: break-word;
        hyphens: auto;
    }
    table.dev-table tbody tr:nth-child(even) {
        background: rgba(255,255,255,0.02);
    }
    table.dev-table tbody tr:hover {
        background: rgba(79, 142, 247, 0.08);
    }
    .dev-table-card--client table.dev-table tbody tr:hover {
        background: rgba(247, 162, 79, 0.08);
    }
    table.dev-table tbody tr:last-child td {
        border-bottom: none;
    }
    .dev-pill-done {
        display: inline-block;
        min-width: 2.5em;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 13px;
        font-weight: 700;
        text-align: center;
    }
    .dev-pill-done--zero {
        background: rgba(255,255,255,0.06);
        color: #6b7288;
    }
    .dev-pill-done--partial {
        background: rgba(82, 212, 142, 0.15);
        color: #52d48e;
        border: 1px solid rgba(82, 212, 142, 0.25);
    }
    .dev-pill-done--full {
        background: rgba(82, 212, 142, 0.22);
        color: #7ef0b3;
        border: 1px solid rgba(82, 212, 142, 0.4);
    }
    .dev-pill-merged {
        background: rgba(167, 139, 250, 0.18);
        color: #c4b5fd;
        border: 1px solid rgba(167, 139, 250, 0.3);
    }
    .dev-pill-qa {
        background: rgba(245, 158, 11, 0.18);
        color: #fbbf24;
        border: 1px solid rgba(245, 158, 11, 0.3);
    }
</style>
""", unsafe_allow_html=True)


# ── Session state init ────────────────────────────────────────────────────────

if "chat_history" not in st.session_state:
    st.session_state.chat_history: list[dict] = []
if "chatbot" not in st.session_state:
    st.session_state.chatbot = None
if "sprints_cache" not in st.session_state:
    st.session_state.sprints_cache: list[dict] | None = None


# ── Data helpers ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=120, show_spinner=False)
def fetch_sprints() -> list[dict]:
    raw = call_tool("get_all_sprints", {"state": "all"})
    data = json.loads(raw)
    if isinstance(data, list):
        return data
    return []


@st.cache_data(ttl=60, show_spinner=False)
def fetch_comparison(sprint_id: int | None) -> dict:
    raw = call_tool("get_team_comparison", {"sprint_id": sprint_id} if sprint_id else {})
    return json.loads(raw)


@st.cache_data(ttl=60, show_spinner=False)
def fetch_sprint_issues(sprint_id: int | None) -> dict:
    raw = call_tool("get_sprint_issues", {"sprint_id": sprint_id} if sprint_id else {})
    return json.loads(raw)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_velocity(num_sprints: int) -> list[dict]:
    raw = call_tool("get_team_velocity", {"num_sprints": num_sprints})
    data = json.loads(raw)
    return data if isinstance(data, list) else []


@st.cache_data(ttl=300, show_spinner=False)
def load_release_calendar() -> pd.DataFrame:
    """Load optional release-calendar CSV used for CXO date-range analytics."""
    csv_path = Path(__file__).with_name("release_calendar.csv")
    if not csv_path.exists():
        return pd.DataFrame()
    # Auto-detect delimiter so both CSV (comma) and pasted TSV work.
    df = pd.read_csv(csv_path, sep=None, engine="python")
    if df.empty:
        return df

    # Normalize common date columns from release plan spreadsheets.
    for col in ("Sprint Start Date", "Dev Done Date", "Sprit End Date", "Sprint End Date", "Deployment"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    if "Deployment" in df.columns:
        # Group FixVersions by the Wednesday "dev done" month, not Monday deployment month,
        # so e.g. 6.3 (dev done Feb, deploy early March) stays with February, not with 7.x in March.
        if "Dev Done Date" in df.columns:
            month_source = df["Dev Done Date"].fillna(df["Deployment"])
        else:
            month_source = df["Deployment"]
        df["Month"] = month_source.dt.to_period("M").astype("string")
    return df


def _fixversion_major(version: str) -> int | None:
    """Leading numeric segment, e.g. '7.1' -> 7, '4.08-performance' -> 4. Unparseable -> None."""
    raw = str(version).strip().split("-", maxsplit=1)[0].strip()
    head = raw.split(".", maxsplit=1)[0] if raw else ""
    return int(head) if head.isdigit() else None


def _filter_fix_versions_single_train(versions: list[str]) -> list[str]:
    """When a month mixes majors (e.g. 7.0-7.3 and 8.0), keep only the lowest-major train."""
    unique = sorted({v for v in versions if v and str(v).strip()})
    if len(unique) <= 1:
        return unique
    by_major: dict[int, list[str]] = {}
    for v in unique:
        m = _fixversion_major(v)
        if m is None:
            return unique
        by_major.setdefault(m, []).append(v)
    if len(by_major) <= 1:
        return unique
    low = min(by_major)
    return sorted(by_major[low])


def fetch_fixversion_coverage(fix_versions: tuple[str, ...]) -> dict:
    raw = call_tool("get_fixversion_coverage", {"fix_versions": list(fix_versions)})
    data = json.loads(raw)
    # Recover from stale in-process registry during hot-reload sessions.
    if isinstance(data, dict) and "error" in data and "Tool 'get_fixversion_coverage' not found" in str(data["error"]):
        importlib.reload(mcp_client)
        retry_raw = mcp_client.call_tool("get_fixversion_coverage", {"fix_versions": list(fix_versions)})
        return json.loads(retry_raw)
    return data


@st.cache_data(ttl=300, show_spinner=False)
def fetch_fixversion_issues(fix_versions: tuple[str, ...]) -> dict:
    raw = call_tool("get_fixversion_issues", {"fix_versions": list(fix_versions)})
    data = json.loads(raw)
    if isinstance(data, dict) and "error" in data and "Tool 'get_fixversion_issues' not found" in str(data["error"]):
        importlib.reload(mcp_client)
        retry_raw = mcp_client.call_tool("get_fixversion_issues", {"fix_versions": list(fix_versions)})
        return json.loads(retry_raw)
    return data


def _status_match_set(canonical: str) -> set[str]:
    """Lowercase Jira status strings for a synonym group (config.STATUS_FILTER_SYNONYMS)."""
    syn = getattr(config, "STATUS_FILTER_SYNONYMS", None) or {}
    aliases = syn.get(canonical, []) or []
    names = [canonical] + list(aliases)
    return {str(x).strip().lower() for x in names if x and str(x).strip()}


def _workflow_stage(
    status: str,
    done: bool,
    merged_s: set[str],
    qa_s: set[str],
    wont_fix_s: set[str],
    review_s: set[str],
    inprog_s: set[str],
    todo_s: set[str],
) -> str:
    """Bucket issues using STATUS_FILTER_SYNONYMS. Unlisted Jira statuses -> Other (not Under Review)."""
    s = str(status).strip().lower()
    if s in wont_fix_s:
        return "Won't Fix"
    if done:
        return "Done"
    if s in merged_s:
        return "Merged"
    if s in qa_s:
        return "QA"
    if s in review_s:
        return "Under Review"
    if s in inprog_s:
        return "In Progress"
    if s in todo_s:
        return "To Do"
    return "Other"


def team_workflow_stage_df(issues: list[dict]) -> pd.DataFrame:
    """Story points by Josh vs Client × workflow stage (STATUS_FILTER_SYNONYMS)."""
    merged_s = _status_match_set("Merged")
    qa_s = _status_match_set("QA")
    wont_fix_s = _status_match_set("Won't Fix")
    review_s = _status_match_set("Under Review")
    inprog_s = _status_match_set("In Progress")
    todo_s = _status_match_set("To Do")
    rows: list[dict] = []
    for i in issues:
        team = i.get("team")
        if team not in ("Josh Team", "Client Team"):
            continue
        pts = float(i.get("storyPoints") or 0)
        stg = _workflow_stage(
            str(i.get("status", "")),
            bool(i.get("done")),
            merged_s,
            qa_s,
            wont_fix_s,
            review_s,
            inprog_s,
            todo_s,
        )
        rows.append({"Team": team, "Stage": stg, "Points": pts})
    if not rows:
        return pd.DataFrame(columns=["Team", "Stage", "Points"])
    return pd.DataFrame(rows).groupby(["Team", "Stage"], as_index=False)["Points"].sum()


def build_comparison_from_issues(issues: list[dict]) -> dict:
    """Build team comparison payload from generic issue rows."""
    teams: dict[str, dict] = {
        "Josh Team": {"planned": 0.0, "completed": 0.0, "members": {}},
        "Client Team": {"planned": 0.0, "completed": 0.0, "members": {}},
        "Other": {"planned": 0.0, "completed": 0.0, "members": {}},
    }
    for issue in issues:
        team = issue.get("team", "Other")
        if team not in teams:
            team = "Other"
        pts = float(issue.get("storyPoints") or 0.0)
        done = bool(issue.get("done"))
        dev_name = issue.get("developerName") or "Unassigned"

        t = teams[team]
        t["planned"] += pts
        if done:
            t["completed"] += pts

        member = t["members"].setdefault(dev_name, {"planned": 0.0, "completed": 0.0, "issues": 0})
        member["planned"] += pts
        member["issues"] += 1
        if done:
            member["completed"] += pts

    summary: dict[str, dict] = {}
    for team_name, t in teams.items():
        planned = t["planned"]
        completed = t["completed"]
        summary[team_name] = {
            "planned": planned,
            "completed": completed,
            "completionPct": round((completed / planned * 100) if planned else 0, 1),
            "members": t["members"],
        }
    return {"comparison": summary}


def _fmt_table_number(val) -> str:
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return "—"
        f = float(val)
        if f == int(f):
            return str(int(f))
        return str(f)
    except (TypeError, ValueError):
        return html_module.escape(str(val))


def _completed_pill_class(planned: float, completed: float) -> str:
    if planned <= 0:
        return "dev-pill-done--zero"
    if completed >= planned > 0:
        return "dev-pill-done--full"
    if completed > 0:
        return "dev-pill-done--partial"
    return "dev-pill-done--zero"


def _status_filter_match_set(selected: list[str]) -> set[str]:
    """
    Build lowercase status strings that count as a match for the multiselect.
    Case-insensitive + expands STATUS_FILTER_SYNONYMS groups when any member is selected.
    """
    selected_l = {str(s).strip().lower() for s in selected if s and str(s).strip()}
    if not selected_l:
        return set()
    match = set(selected_l)
    syn = getattr(config, "STATUS_FILTER_SYNONYMS", None) or {}
    for canonical, aliases in syn.items():
        group = {str(canonical).strip().lower()} | {
            str(a).strip().lower() for a in (aliases or []) if a and str(a).strip()
        }
        if selected_l & group:
            match |= group
    return match


def render_developer_table(df: pd.DataFrame, variant: str, label: str) -> None:
    """Styled HTML table for Josh / Client developer breakdown (variant: josh | client)."""
    if df.empty:
        return
    card_class = "dev-table-card--josh" if variant == "josh" else "dev-table-card--client"
    rows_html = []
    for _, row in df.iterrows():
        dev = html_module.escape(str(row.get("Developer", "")))
        planned = float(row.get("Planned", 0) or 0)
        completed = float(row.get("Completed", 0) or 0)
        todo_pts = float(row.get("To Do", 0) or 0)
        inprog_pts = float(row.get("In Progress", 0) or 0)
        under_review = float(row.get("Under Review", 0) or 0)
        other_st = float(row.get("Other", 0) or 0)
        merged = float(row.get("Merged", 0) or 0)
        qa = float(row.get("QA", 0) or 0)
        wont_fix = float(row.get("Won't Fix", 0) or 0)
        remaining = float(row.get("Remaining", 0) or 0)
        done_pct = html_module.escape(str(row.get("Done %", "0%")))
        try:
            issues_display = str(int(float(row.get("Issues", 0) or 0)))
        except (TypeError, ValueError):
            issues_display = html_module.escape(str(row.get("Issues", "")))
        pill = _completed_pill_class(planned, completed)
        td_cls = "dev-pill-done--partial" if todo_pts > 0 else "dev-pill-done--zero"
        ip_cls = "dev-pill-done--partial" if inprog_pts > 0 else "dev-pill-done--zero"
        ur_cls = "dev-pill-done--partial" if under_review > 0 else "dev-pill-done--zero"
        oth_cls = "dev-pill-done--partial" if other_st > 0 else "dev-pill-done--zero"
        merged_cls = "dev-pill-done--partial" if merged > 0 else "dev-pill-done--zero"
        qa_cls = "dev-pill-done--partial" if qa > 0 else "dev-pill-done--zero"
        wf_cls = "dev-pill-done--partial" if wont_fix > 0 else "dev-pill-done--zero"
        rows_html.append(
            f"<tr>"
            f'<td class="dev-name">{dev}</td>'
            f'<td class="num">{_fmt_table_number(planned)}</td>'
            f'<td class="num"><span class="dev-pill-done {pill}">{_fmt_table_number(completed)}</span></td>'
            f'<td class="num"><span class="dev-pill-done {td_cls}">{_fmt_table_number(todo_pts)}</span></td>'
            f'<td class="num"><span class="dev-pill-done {ip_cls}">{_fmt_table_number(inprog_pts)}</span></td>'
            f'<td class="num"><span class="dev-pill-done {ur_cls}">{_fmt_table_number(under_review)}</span></td>'
            f'<td class="num"><span class="dev-pill-done {oth_cls}">{_fmt_table_number(other_st)}</span></td>'
            f'<td class="num"><span class="dev-pill-done {merged_cls}">{_fmt_table_number(merged)}</span></td>'
            f'<td class="num"><span class="dev-pill-done {qa_cls}">{_fmt_table_number(qa)}</span></td>'
            f'<td class="num"><span class="dev-pill-done {wf_cls}">{_fmt_table_number(wont_fix)}</span></td>'
            f'<td class="num">{_fmt_table_number(remaining)}</td>'
            f'<td class="num">{done_pct}</td>'
            f'<td class="num">{issues_display}</td>'
            f"</tr>"
        )
    table_inner = (
        f'<div class="dev-table-card {card_class}">'
        f'<div class="dev-table-card__head"><span class="dev-table-card__accent"></span>'
        f"<span>{html_module.escape(label)}</span></div>"
        '<div class="dev-table-card__scroll">'
        "<table class='dev-table'><thead><tr>"
        "<th>Developer</th>"
        '<th class="num">Planned</th>'
        '<th class="num">Completed</th>'
        '<th class="num">To Do</th>'
        '<th class="num">In Progress</th>'
        '<th class="num">Under Review</th>'
        '<th class="num">Other</th>'
        '<th class="num">Merged</th>'
        '<th class="num">QA</th>'
        '<th class="num">Won\'t Fix</th>'
        '<th class="num">Remaining</th>'
        '<th class="num">Done %</th>'
        '<th class="num">Issues</th>'
        "</tr></thead><tbody>"
        + "".join(rows_html)
        + "</tbody></table></div></div>"
    )
    st.markdown(table_inner, unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────

selected_release_month = None
selected_release_fix_versions: tuple[str, ...] = ()

with st.sidebar:
    st.image("https://cdn.worldvectorlogo.com/logos/jira-1.svg", width=40)
    st.title("SprintTrace")
    st.caption(f"Project: **{config.JIRA_PROJECT_KEY or 'Not set'}**")

    # Sprint selector removed from UI; sprint-based tools default to active sprint.
    selected_sprint_id = None
    selected_sprint_label = "Current Active Sprint"

    st.divider()
    st.subheader("Release Month")
    release_df = load_release_calendar()
    if release_df.empty:
        st.caption("Add `release_calendar.csv` to enable month-wise coverage by FixVersion.")
    elif "Month" not in release_df.columns or "FixVersion" not in release_df.columns:
        st.warning("release_calendar.csv is missing `Deployment` or `FixVersion` columns.")
    else:
        month_options = sorted(
            [m for m in release_df["Month"].dropna().unique().tolist() if str(m).strip()],
            reverse=True,
        )
        if month_options:
            current_month_label = (
                pd.Series([pd.Timestamp.now()], dtype="datetime64[ns]")
                .dt.to_period("M")
                .astype("string")
                .iloc[0]
            )
            default_month_index = (
                month_options.index(current_month_label)
                if current_month_label in month_options
                else 0
            )
            selected_release_month = st.selectbox(
                "Select month",
                month_options,
                index=default_month_index,
                help="Uses Dev Done Date month (Wednesday) when set, else Deployment month, from release_calendar.csv. "
                "Defaults to this calendar month when present.",
            )
            month_rows = release_df[release_df["Month"] == selected_release_month]
            versions = sorted(
                {
                    str(v).strip()
                    for v in month_rows["FixVersion"].dropna().tolist()
                    if str(v).strip()
                }
            )
            versions = _filter_fix_versions_single_train(versions)
            selected_release_fix_versions = tuple(versions)
            st.caption(f"FixVersions in month: {', '.join(versions) if versions else '—'}")
        else:
            st.caption("No month values found in `Deployment` column.")

    # Config warnings
    if not config.JIRA_API_TOKEN:
        st.error("⚠️ JIRA_API_TOKEN not set in .env")
    if not config.JOSH_TEAM_MEMBERS and not config.CLIENT_TEAM_MEMBERS:
        st.warning("⚠️ No team members configured in config.py — add display names to JOSH_TEAM_MEMBERS and CLIENT_TEAM_MEMBERS")

    st.divider()
    velocity_lookback = st.slider("Velocity lookback (sprints)", 3, 12, config.VELOCITY_SPRINTS_LOOKBACK)

    st.divider()
    if st.button("🔄 Refresh Data", width="stretch", help="Clear cached Jira data and reload"):
        st.cache_data.clear()
        st.session_state.chatbot = None
        st.rerun()


# ── Main content ──────────────────────────────────────────────────────────────

tab_dashboard, tab_issues, tab_chatbot = st.tabs([
    "📊  Team Comparison", "🗂  Sprint Issues", "🤖  AI Assistant"
])


# ════════════════════════════════════════════════════════════════════════════
# TAB 1: TEAM COMPARISON DASHBOARD
# ════════════════════════════════════════════════════════════════════════════

with tab_dashboard:
    if selected_release_month and selected_release_fix_versions:
        with st.spinner("Calculating release month coverage..."):
            cov = fetch_fixversion_coverage(selected_release_fix_versions)
        if "error" in cov:
            st.error(f"Release-month coverage error: {cov['error']}")
        else:
            st.subheader(f"Release Coverage — {selected_release_month}")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("FixVersions", len(cov.get("fixVersions", [])))
            c2.metric("Planned Points", round(float(cov.get("planned", 0.0)), 1))
            c3.metric("Covered Points", round(float(cov.get("completed", 0.0)), 1))
            c4.metric("Coverage %", f"{cov.get('coveragePct', 0)}%")
            per_team = cov.get("perTeam", {}) if isinstance(cov, dict) else {}
            j_cov = per_team.get("Josh Team", {}) if isinstance(per_team, dict) else {}
            c_cov = per_team.get("Client Team", {}) if isinstance(per_team, dict) else {}
            tc1, tc2 = st.columns(2)
            with tc1:
                st.markdown("**Josh Team Coverage**")
                tj1, tj2, tj3 = st.columns(3)
                tj1.metric("Planned", round(float(j_cov.get("planned", 0.0)), 1))
                tj2.metric("Covered", round(float(j_cov.get("completed", 0.0)), 1))
                tj3.metric("Coverage", f"{j_cov.get('coveragePct', 0)}%")
            with tc2:
                st.markdown("**Client Team Coverage**")
                tcj1, tcj2, tcj3 = st.columns(3)
                tcj1.metric("Planned", round(float(c_cov.get("planned", 0.0)), 1))
                tcj2.metric("Covered", round(float(c_cov.get("completed", 0.0)), 1))
                tcj3.metric("Coverage", f"{c_cov.get('coveragePct', 0)}%")
            st.caption("Coverage is based on Jira done-status category for issues in selected FixVersions.")
            st.divider()

    if selected_release_month:
        st.header(f"Release Month: {selected_release_month}")
    else:
        st.header(f"Sprint: {selected_sprint_label}")

    # Fetch dashboard source data
    with st.spinner("Fetching data..."):
        sprint_issues_for_chart: list[dict] = []
        if selected_release_month and selected_release_fix_versions:
            idata = fetch_fixversion_issues(selected_release_fix_versions)
            if "error" in idata:
                comp_data = {"error": idata["error"]}
            else:
                sprint_issues_for_chart = idata.get("issues", [])
                comp_data = build_comparison_from_issues(sprint_issues_for_chart)
        else:
            comp_data = fetch_comparison(selected_sprint_id)
            if "error" not in comp_data:
                idata = fetch_sprint_issues(selected_sprint_id)
                if "error" not in idata:
                    sprint_issues_for_chart = idata.get("issues", [])

    if "error" in comp_data:
        st.error(f"Jira error: {comp_data['error']}")
    else:
        comp = comp_data.get("comparison", {})
        josh = comp.get("Josh Team", {"planned": 0, "completed": 0, "completionPct": 0, "members": {}})
        client = comp.get("Client Team", {"planned": 0, "completed": 0, "completionPct": 0, "members": {}})

        # ── KPI Metrics ──
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Josh Team — Planned", f"{josh['planned']} pts")
        with col2:
            delta_j = f"{josh['completionPct']}% done"
            st.metric("Josh Team — Completed", f"{josh['completed']} pts", delta=delta_j)
        with col3:
            st.metric("Client Team — Planned", f"{client['planned']} pts")
        with col4:
            delta_c = f"{client['completionPct']}% done"
            st.metric("Client Team — Completed", f"{client['completed']} pts", delta=delta_c)

        st.divider()

        # ── Comparison bar chart ──
        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader(
                "Story points by stage (To Do · In Progress · Under Review · Other · Won't Fix · Merged · QA · Done)"
            )
            st.caption(
                "**Under Review** = only statuses in that synonym group (e.g. PR Review). "
                "**Other** = story points in Jira statuses not mapped in config.py — add them to the right group there."
            )
            stage_df = team_workflow_stage_df(sprint_issues_for_chart)
            if stage_df.empty:
                st.info("No Josh/Client issues in this sprint for the stage chart.")
            else:
                stage_order = [
                    "To Do",
                    "In Progress",
                    "Under Review",
                    "Other",
                    "Won't Fix",
                    "Merged",
                    "QA",
                    "Done",
                ]
                stage_colors = {
                    "To Do": "#64748b",
                    "In Progress": "#0ea5e9",
                    "Under Review": "#5c6b7a",
                    "Other": "#475569",
                    "Won't Fix": "#ef4444",
                    "Merged": "#a78bfa",
                    "QA": "#f59e0b",
                    "Done": "#52d48e",
                }
                fig_stage = px.bar(
                    stage_df,
                    x="Team",
                    y="Points",
                    color="Stage",
                    barmode="stack",
                    category_orders={"Stage": stage_order},
                    color_discrete_map=stage_colors,
                    template="plotly_dark",
                )
                fig_stage.update_layout(
                    margin=dict(l=0, r=0, t=12, b=0),
                    legend=dict(orientation="h", y=1.12, title_text=""),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    yaxis_title="Story points",
                    uniformtext_minsize=10,
                    uniformtext_mode="hide",
                )
                st.plotly_chart(fig_stage, width="stretch", config=PLOTLY_CHART_CONFIG)

            st.subheader("Planned vs stages (grouped)")
            bar_rows: list[dict] = []
            stage_types = [
                "To Do",
                "In Progress",
                "Under Review",
                "Other",
                "Won't Fix",
                "Merged",
                "QA",
                "Done",
            ]
            for team_name, pdata in [("Josh Team", josh), ("Client Team", client)]:
                bar_rows.append({"Team": team_name, "Type": "Planned", "Points": pdata["planned"]})
                for stg in stage_types:
                    pts = 0.0
                    if not stage_df.empty:
                        sel = stage_df[(stage_df["Team"] == team_name) & (stage_df["Stage"] == stg)]["Points"]
                        pts = float(sel.sum()) if len(sel) else 0.0
                    bar_rows.append({"Team": team_name, "Type": stg, "Points": pts})
            bar_df = pd.DataFrame(bar_rows)
            bar_type_order = ["Planned"] + stage_types
            bar_colors = {
                "Planned": "#4f8ef7",
                "To Do": "#64748b",
                "In Progress": "#0ea5e9",
                "Under Review": "#5c6b7a",
                "Other": "#475569",
                "Won't Fix": "#ef4444",
                "Merged": "#a78bfa",
                "QA": "#f59e0b",
                "Done": "#52d48e",
            }
            fig_bar = px.bar(
                bar_df, x="Team", y="Points", color="Type", barmode="group",
                category_orders={"Type": bar_type_order},
                color_discrete_map=bar_colors,
                template="plotly_dark",
            )
            fig_bar.update_layout(
                margin=dict(l=0, r=0, t=20, b=0),
                legend=dict(orientation="h", y=1.18, title_text=""),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                yaxis_title="Story points",
            )
            st.caption(
                "**Planned** = all sprint points. Stages include **Other** for unmapped Jira statuses "
                "(should add up to Planned per team). **Done** matches KPI completed."
            )
            st.plotly_chart(fig_bar, width="stretch", config=PLOTLY_CHART_CONFIG)

        with col_right:
            st.subheader("Completion %")
            for team_name, team_data, color in [
                ("Josh Team", josh, "#4f8ef7"),
                ("Client Team", client, "#f7a24f"),
            ]:
                pct = team_data["completionPct"]
                done = team_data["completed"]
                planned = team_data["planned"]
                remaining = max(0, planned - done)
                bar_html = f"""
                <div style="margin-bottom:18px;">
                  <div style="display:flex;justify-content:space-between;
                              align-items:baseline;margin-bottom:6px;">
                    <span style="color:{color};font-weight:700;font-size:15px;">
                      {team_name}
                    </span>
                    <span style="color:{color};font-size:26px;font-weight:800;
                                 letter-spacing:-1px;">
                      {pct}%
                    </span>
                  </div>
                  <div style="background:#1e2130;border-radius:8px;
                              height:14px;overflow:hidden;">
                    <div style="width:{min(pct,100)}%;height:100%;
                                background:{color};border-radius:8px;
                                transition:width 0.5s ease;">
                    </div>
                  </div>
                  <div style="display:flex;justify-content:space-between;
                              margin-top:5px;font-size:12px;color:#8b95b0;">
                    <span>✅ {done} pts done</span>
                    <span>⏳ {remaining} pts remaining</span>
                    <span>📋 {planned} pts total</span>
                  </div>
                </div>
                """
                st.markdown(bar_html, unsafe_allow_html=True)

        st.divider()

        # ── Per-member tables (with Merged / QA columns) ──
        col_jm, col_cm = st.columns(2)

        _merged_set = _status_match_set("Merged")
        _qa_set = _status_match_set("QA")
        _wont_fix_set = _status_match_set("Won't Fix")
        _review_set = _status_match_set("Under Review")
        _inprog_set = _status_match_set("In Progress")
        _todo_set = _status_match_set("To Do")

        def _dev_stage_points(issues: list[dict], team_filter: str) -> dict[str, dict[str, float]]:
            """From raw sprint issues, compute per-developer stage points."""
            empty = {
                "To Do": 0.0,
                "In Progress": 0.0,
                "Under Review": 0.0,
                "Other": 0.0,
                "Merged": 0.0,
                "QA": 0.0,
                "Won't Fix": 0.0,
            }
            agg: dict[str, dict[str, float]] = {}
            for iss in issues:
                if iss.get("team") != team_filter:
                    continue
                dev = iss.get("developerName") or "Unassigned"
                pts = float(iss.get("storyPoints") or 0)
                stage = _workflow_stage(
                    str(iss.get("status", "")),
                    bool(iss.get("done")),
                    _merged_set,
                    _qa_set,
                    _wont_fix_set,
                    _review_set,
                    _inprog_set,
                    _todo_set,
                )
                bucket = agg.setdefault(dev, dict(empty))
                if stage == "To Do":
                    bucket["To Do"] += pts
                elif stage == "In Progress":
                    bucket["In Progress"] += pts
                elif stage == "Under Review":
                    bucket["Under Review"] += pts
                elif stage == "Other":
                    bucket["Other"] += pts
                elif stage == "Merged":
                    bucket["Merged"] += pts
                elif stage == "QA":
                    bucket["QA"] += pts
                elif stage == "Won't Fix":
                    bucket["Won't Fix"] += pts
            return agg

        josh_stages = _dev_stage_points(sprint_issues_for_chart, "Josh Team")
        client_stages = _dev_stage_points(sprint_issues_for_chart, "Client Team")

        def members_df(
            members: dict,
            stage_map: dict[str, dict[str, float]],
            include_names: list[str] | None = None,
        ) -> pd.DataFrame:
            rows = []
            ordered_names: list[str] = []
            if include_names:
                ordered_names.extend([n for n in include_names if n and n not in ordered_names])
            ordered_names.extend([n for n in members.keys() if n and n not in ordered_names])

            for name in ordered_names:
                stats = members.get(name, {})
                planned = stats.get("planned", 0)
                done = stats.get("completed", 0)
                dev_stages = stage_map.get(name, {})
                rows.append({
                    "Member": name,
                    "Planned": planned,
                    "Completed": done,
                    "To Do": dev_stages.get("To Do", 0),
                    "In Progress": dev_stages.get("In Progress", 0),
                    "Under Review": dev_stages.get("Under Review", 0),
                    "Other": dev_stages.get("Other", 0),
                    "Merged": dev_stages.get("Merged", 0),
                    "QA": dev_stages.get("QA", 0),
                    "Won't Fix": dev_stages.get("Won't Fix", 0),
                    "Remaining": max(0, planned - done),
                    "Done %": f"{round(done / planned * 100) if planned else 0}%",
                    "Issues": stats.get("issues", 0),
                })
            df = pd.DataFrame(rows)
            if not df.empty and "Planned" in df.columns:
                df = df.sort_values("Planned", ascending=False)
            return df

        with col_jm:
            df_j = members_df(
                josh.get("members", {}),
                josh_stages,
                include_names=getattr(config, "JOSH_TEAM_MEMBERS", []),
            )
            if not df_j.empty:
                render_developer_table(
                    df_j.rename(columns={"Member": "Developer"}),
                    "josh",
                    "Josh Team — Developers",
                )
            else:
                st.info("No Josh Team developers found.")

        with col_cm:
            df_c = members_df(
                client.get("members", {}),
                client_stages,
                include_names=getattr(config, "CLIENT_TEAM_MEMBERS", []),
            )
            if not df_c.empty:
                render_developer_table(
                    df_c.rename(columns={"Member": "Developer"}),
                    "client",
                    "Client Team — Developers",
                )
            else:
                st.info("No Client Team developers found.")

        st.divider()

        # ── Velocity trend (same chart whether or not a release month is selected) ──
        st.subheader(f"Velocity Trend — Last {velocity_lookback} Sprints")
        with st.spinner("Loading velocity..."):
            velocity_data = fetch_velocity(velocity_lookback)

        if velocity_data:
            vel_df = pd.DataFrame(velocity_data)
            fig_vel = go.Figure()
            fig_vel.add_trace(go.Scatter(
                x=vel_df["sprintName"], y=vel_df["joshCompleted"],
                name="Josh Completed", line=dict(color="#4f8ef7", width=2),
                mode="lines+markers",
            ))
            fig_vel.add_trace(go.Scatter(
                x=vel_df["sprintName"], y=vel_df["joshPlanned"],
                name="Josh Planned", line=dict(color="#4f8ef7", width=1, dash="dash"),
                mode="lines+markers",
            ))
            fig_vel.add_trace(go.Scatter(
                x=vel_df["sprintName"], y=vel_df["clientCompleted"],
                name="Client Completed", line=dict(color="#f7a24f", width=2),
                mode="lines+markers",
            ))
            fig_vel.add_trace(go.Scatter(
                x=vel_df["sprintName"], y=vel_df["clientPlanned"],
                name="Client Planned", line=dict(color="#f7a24f", width=1, dash="dash"),
                mode="lines+markers",
            ))
            fig_vel.update_layout(
                template="plotly_dark",
                xaxis_title="Sprint",
                yaxis_title="Story Points",
                legend=dict(orientation="h", y=1.1),
                margin=dict(l=0, r=0, t=40, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_vel, width="stretch", config=PLOTLY_CHART_CONFIG)
        else:
            st.info("No closed sprints found for velocity chart.")

        # ── Export ──
        st.divider()
        st.subheader("Export Report")
        ec1, ec2 = st.columns(2)

        with ec1:
            if st.button("📥 Download Excel Report", width="stretch"):
                with st.spinner("Generating report..."):
                    report_raw = call_tool(
                        "generate_sprint_report",
                        {"sprint_id": selected_sprint_id} if selected_sprint_id else {},
                    )
                    report = json.loads(report_raw)

                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                    # Summary sheet
                    summary_df = pd.DataFrame([
                        {"Metric": "Sprint", "Value": report.get("sprintName", "")},
                        {"Metric": "Generated At", "Value": report.get("generatedAt", "")},
                        {"Metric": "Josh Planned", "Value": report.get("comparison", {}).get("Josh Team", {}).get("planned", 0)},
                        {"Metric": "Josh Completed", "Value": report.get("comparison", {}).get("Josh Team", {}).get("completed", 0)},
                        {"Metric": "Josh Completion %", "Value": report.get("comparison", {}).get("Josh Team", {}).get("completionPct", 0)},
                        {"Metric": "Client Planned", "Value": report.get("comparison", {}).get("Client Team", {}).get("planned", 0)},
                        {"Metric": "Client Completed", "Value": report.get("comparison", {}).get("Client Team", {}).get("completed", 0)},
                        {"Metric": "Client Completion %", "Value": report.get("comparison", {}).get("Client Team", {}).get("completionPct", 0)},
                    ])
                    summary_df.to_excel(writer, sheet_name="Summary", index=False)

                    # Issues sheets
                    all_issues = report.get("completedIssues", []) + report.get("incompleteIssues", [])
                    if all_issues:
                        issues_df = pd.DataFrame(all_issues)
                        issues_df.to_excel(writer, sheet_name="All Issues", index=False)

                    completed_issues = report.get("completedIssues", [])
                    if completed_issues:
                        pd.DataFrame(completed_issues).to_excel(writer, sheet_name="Completed", index=False)

                    incomplete_issues = report.get("incompleteIssues", [])
                    if incomplete_issues:
                        pd.DataFrame(incomplete_issues).to_excel(writer, sheet_name="Incomplete", index=False)

                buf.seek(0)
                fname = f"jira_report_{report.get('sprintName', 'sprint').replace(' ', '_')}.xlsx"
                st.download_button(
                    "⬇ Click to Download",
                    data=buf,
                    file_name=fname,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

        with ec2:
            if st.button("📋 Download CSV (Issues)", width="stretch"):
                with st.spinner("Fetching issues..."):
                    issues_data = fetch_sprint_issues(selected_sprint_id)
                issues = issues_data.get("issues", [])
                if issues:
                    csv_buf = io.StringIO()
                    pd.DataFrame(issues).to_csv(csv_buf, index=False)
                    st.download_button(
                        "⬇ Click to Download",
                        data=csv_buf.getvalue(),
                        file_name=f"jira_issues_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime="text/csv",
                    )
                else:
                    st.warning("No issues to export.")


# ════════════════════════════════════════════════════════════════════════════
# TAB 2: SPRINT ISSUES TABLE
# ════════════════════════════════════════════════════════════════════════════

with tab_issues:
    st.header(f"Sprint Issues — {selected_sprint_label}")

    with st.spinner("Loading issues..."):
        issues_data = fetch_sprint_issues(selected_sprint_id)

    issues: list = []
    df_issues = pd.DataFrame()
    status_options: list[str] = []

    if "error" not in issues_data:
        issues = issues_data.get("issues", [])
        df_issues = pd.DataFrame(issues) if issues else pd.DataFrame()
        from_sprint: set[str] = set()
        if not df_issues.empty and "status" in df_issues.columns:
            from_sprint = {
                str(s).strip()
                for s in df_issues["status"].dropna().unique()
                if str(s).strip()
            }
        preset_set = {s.strip() for s in config.SPRINT_ISSUES_STATUS_PRESETS if s.strip()}
        status_options = sorted(
            preset_set | from_sprint,
            key=lambda x: x.lower(),
        )

    # Filters (after load so Status lists presets + real sprint statuses)
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        default_teams = (
            ["Josh Team", "Client Team"]
            if (config.JOSH_TEAM_MEMBERS or config.CLIENT_TEAM_MEMBERS)
            else ["Josh Team", "Client Team", "Other"]
        )
        team_filter = st.multiselect(
            "Team", ["Josh Team", "Client Team", "Other"], default=default_teams
        )
    with fc2:
        status_filter = st.multiselect(
            "Status",
            options=status_options,
            default=[],
            help=(
                "Leave empty for all. Matching is case-insensitive; "
                "e.g. Under Review also matches PR Review / In Review (see STATUS_FILTER_SYNONYMS in config.py)."
            ),
        )
    with fc3:
        search_term = st.text_input("Search summary", placeholder="keyword...")

    if "error" in issues_data:
        st.error(f"Jira error: {issues_data['error']}")
    elif not df_issues.empty:
        if team_filter:
            df_issues = df_issues[df_issues["team"].isin(team_filter)]
        if status_filter:
            match_set = _status_filter_match_set(status_filter)
            norm_status = df_issues["status"].astype(str).str.strip().str.lower()
            df_issues = df_issues[norm_status.isin(match_set)]
        if search_term:
            df_issues = df_issues[
                df_issues["summary"].str.contains(search_term, case=False, na=False)
            ]

        st.caption(f"Showing {len(df_issues)} of {len(issues)} issues")

        display_cols = ["key", "summary", "developerName", "team", "status", "storyPoints", "done", "issueType"]
        display_cols = [c for c in display_cols if c in df_issues.columns]

        st.dataframe(
            df_issues[display_cols].rename(columns={
                "key": "Key",
                "summary": "Summary",
                "developerName": "Developer",
                "team": "Team",
                "status": "Status",
                "storyPoints": "Points",
                "done": "Done",
                "issueType": "Type",
            }),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No issues found for the selected sprint.")


# ════════════════════════════════════════════════════════════════════════════
# TAB 3: AI CHATBOT
# ════════════════════════════════════════════════════════════════════════════

with tab_chatbot:
    # Init chatbot lazily
    if st.session_state.chatbot is None:
        if config.OPENAI_API_KEY:
            from chatbot import JiraChatbot
            st.session_state.chatbot = JiraChatbot()
        else:
            st.error("OPENAI_API_KEY not set in .env — chatbot unavailable.")

    # ── Quick-action pill buttons ──
    qa_cols = st.columns(6)
    quick_q = None
    with qa_cols[0]:
        st.markdown('<div class="quick-action-btn">', unsafe_allow_html=True)
        if st.button("Sprint summary"):
            quick_q = "Give me a summary of the current sprint performance for both teams."
        st.markdown('</div>', unsafe_allow_html=True)
    with qa_cols[1]:
        st.markdown('<div class="quick-action-btn">', unsafe_allow_html=True)
        if st.button("Josh velocity"):
            quick_q = "What is Josh team's velocity trend over the last 6 sprints?"
        st.markdown('</div>', unsafe_allow_html=True)
    with qa_cols[2]:
        st.markdown('<div class="quick-action-btn">', unsafe_allow_html=True)
        if st.button("Incomplete issues"):
            quick_q = "List all incomplete issues in the current sprint with their story points."
        st.markdown('</div>', unsafe_allow_html=True)
    with qa_cols[3]:
        st.markdown('<div class="quick-action-btn">', unsafe_allow_html=True)
        if st.button("Generate report"):
            quick_q = "Generate a full sprint report for the current sprint."
        st.markdown('</div>', unsafe_allow_html=True)
    with qa_cols[4]:
        st.markdown('<div class="quick-action-btn">', unsafe_allow_html=True)
        if st.button("🗑 Clear"):
            st.session_state.chat_history = []
            if st.session_state.chatbot:
                st.session_state.chatbot.clear_history()
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    with qa_cols[5]:
        st.markdown('<div class="quick-action-btn">', unsafe_allow_html=True)
        if st.button("📥 Export"):
            with st.spinner("Generating report..."):
                report_raw = call_tool(
                    "generate_sprint_report",
                    {"sprint_id": selected_sprint_id} if selected_sprint_id else {},
                )
                report = json.loads(report_raw)
            if "error" not in report:
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                    all_issues = report.get("completedIssues", []) + report.get("incompleteIssues", [])
                    if all_issues:
                        pd.DataFrame(all_issues).to_excel(writer, sheet_name="Issues", index=False)
                    pd.DataFrame([
                        {"Key": k, "Value": v}
                        for k, v in {
                            "Sprint": report.get("sprintName"),
                            "Generated": report.get("generatedAt"),
                        }.items()
                    ]).to_excel(writer, sheet_name="Summary", index=False)
                buf.seek(0)
                st.download_button(
                    "⬇ Download",
                    data=buf,
                    file_name=f"report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            else:
                st.error(f"Could not generate report: {report['error']}")
        st.markdown('</div>', unsafe_allow_html=True)

    # ── Chat history (Claude-style bubbles via st.chat_message) ──
    if not st.session_state.chat_history:
        with st.chat_message("assistant"):
            st.markdown(
                "Hi there! I'm **SprintTrace**'s AI assistant. Ask me anything about "
                "sprints, story points, team performance, or generate reports."
            )
    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.markdown(msg["content"])
        elif msg["role"] == "assistant":
            with st.chat_message("assistant"):
                st.markdown(msg["content"])
                if msg.get("tools_used"):
                    badges = " ".join(
                        f'<span class="tool-badge">🔧 {t}</span>' for t in msg["tools_used"]
                    )
                    st.markdown(f"<small>{badges}</small>", unsafe_allow_html=True)

    # ── Chat input (native Streamlit chat_input — no "press enter" label) ──
    user_input = st.chat_input("Ask about sprints, story points, team performance...")

    message_to_send = quick_q or user_input

    if message_to_send and st.session_state.chatbot:
        st.session_state.chat_history.append({"role": "user", "content": message_to_send})
        with st.spinner("Thinking..."):
            try:
                reply, tool_log = st.session_state.chatbot.chat(message_to_send)
                tools_used = list({t["tool"] for t in tool_log})
            except Exception as e:
                reply = f"Error: {e}"
                tools_used = []

        st.session_state.chat_history.append({
            "role": "assistant",
            "content": reply,
            "tools_used": tools_used,
        })
        st.rerun()
