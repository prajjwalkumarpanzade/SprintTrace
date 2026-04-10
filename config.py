"""
Central configuration for team membership and app settings.

Team members are matched by **Developer** field display name (case-insensitive), never Assignee.
To find names: run the dashboard Sprint Issues tab and use the **Developer** column.

Example people seen on the board (for reference — verify in Developer field):
    Shyam Pandav, Ketan Sabnis, Prajjwalkumar Panzade, Aryan Pal,
    Anuj Santosh Barave, Sharayu Sutar, anil solankar, Sumit Waman,
    Abhishek Jaiswal, Sakshi Kashyap, Pooja Mane, Vaibhav Bhattad,
    Atharva Banasure, Tanush Abhinav Shah, Aditya Pansare, Harsh Dhawale,
    Aman. Singh, Yash Deepak Anbhore, Rushikesh Dhaygude, Jigar Makwana
"""

from dotenv import load_dotenv
import os

load_dotenv()

# ── Jira connection ──────────────────────────────────────────────────────────
JIRA_URL = os.getenv("JIRA_URL", "")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")
JIRA_BOARD_ID = int(os.getenv("JIRA_BOARD_ID", "1"))
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "")

# ── OpenAI ───────────────────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

# ── Team membership (matched by Developer field display name, case-insensitive) ──
# Uses the "Developer" custom field (customfield_10084), not the Assignee field.
# Add exact display names as they appear in the Developer field in Jira.

JOSH_TEAM_MEMBERS: list[str] = [
    "Prajjwalkumar Panzade",
    "Pooja Mane" ,
    "Tanush Abhinav Shah",
    "Shadab Shikalgar"
]

CLIENT_TEAM_MEMBERS: list[str] = [
  "Aryan Pal",
  "Anuj Santosh Barave",
  "Sumit Waman",
  "Abhishek Jaiswal",
  "Vaibhav Bhattad",
  "Atharva Banasure",
  "Aditya Pansare",
  "Harsh Dhawale",
  "Aman. Singh",
  "Yash Deepak Anbhore",
  "Rushikesh Dhaygude",
  "Jigar Makwana",
  "Mayuresh Nitin Chavan"
]

# ── Team capacity (story-point equivalent) ───────────────────────────────────
# Story points = (CAPACITY_HOURS_PER_MEMBER × dev count) ÷ HOURS_PER_STORY_POINT
# Josh uses fixed JOSH_CAPACITY_DEV_COUNT (3). Client uses number of names in CLIENT_TEAM_MEMBERS.
CAPACITY_HOURS_PER_MEMBER: float = float(os.getenv("CAPACITY_HOURS_PER_MEMBER", "120"))
HOURS_PER_STORY_POINT: float = float(os.getenv("HOURS_PER_STORY_POINT", "6"))
JOSH_CAPACITY_DEV_COUNT: int = int(os.getenv("JOSH_CAPACITY_DEV_COUNT", "3"))

# ── Dashboard settings ───────────────────────────────────────────────────────
VELOCITY_SPRINTS_LOOKBACK = 6   # how many past sprints to show in velocity chart

# Jira board sprint API is paginated (default 50/page). We fetch all pages so recent
# closed sprints (e.g. CRM_2.70) are not missing when hundreds of old sprints exist.
JIRA_SPRINT_PAGE_SIZE = 100

# How many closed sprints to fetch from Jira (from the tail = newest).
# Jira returns oldest-first; we skip to `total - TAIL_SIZE` and grab only this many.
# 50 is plenty for "last 10 CRM_2.6x" sprints with headroom.
JIRA_CLOSED_SPRINT_TAIL_SIZE: int = 50

# After CRM name filter + optional month filter: merge active + closed + future, sort by
# recency (see README), then keep only this many sprints for the dashboard selector.
# Set to None for no cap (not recommended — list can be huge).
DASHBOARD_CLOSED_SPRINT_LIMIT: int | None = 10

# Only show sprints whose name matches CRM_2.<patch> (case-insensitive) with patch >= this.
# E.g. 60 → CRM_2.60, CRM_2.70, CRM_2.71 included; CRM_2.59 and "Defect Fixing Sprint" excluded.
# None = show all sprint names from Jira.
DASHBOARD_SPRINT_MIN_CRM_2_PATCH: int | None = 60

# Optional upper bound for the same pattern (inclusive). E.g. 69 → only CRM_2.60 … CRM_2.69
# (excludes CRM_2.70). None = no upper limit (2.70, 2.71, … still allowed).
DASHBOARD_SPRINT_MAX_CRM_2_PATCH: int | None = None

# Status filter chips on Sprint Issues tab — merged with statuses found in the sprint
SPRINT_ISSUES_STATUS_PRESETS: list[str] = [
    "To Do",
    "In Progress",
    "Done",
    "Merged",
    "QA",
    "Under Review",
    "Won't Fix",
    "Rework",
    "PR Review",
    "Ready to start",
    "Under UAT",
    "Tech Discussion",
    "Estimation Completed",
    "Need Help/Information",
]

# When you pick a status in the Sprint Issues filter, we match case-insensitively and
# also treat these *groups* as the same bucket (Jira names vary by project).
# Key = label in presets; values = other status names on your board that belong with it.
# Add your exact Jira status strings here if a filter still shows nothing.
# Dashboard stage charts: any Jira status not matching a group below is counted as **Other**
# (not Under Review). Under Review points = only this status + its aliases.
STATUS_FILTER_SYNONYMS: dict[str, list[str]] = {
    "Under Review": [
        "PR Review",
        "In Review",
        "Code Review",
        "Review",
        "Peer Review",
        "Dev Review",
    ],
    "QA": [
        "Qa",
        "Testing",
        "In QA",
        "Ready for QA",
        "Quality Assurance",
    ],
    "Merged": [
        "Merge",
        "Merged to develop",
        "Merged to main",
    ],
    "Won't Fix": [
        "Wont Fix",
        "Won't Do",
        "Cancelled",
        "Canceled",
        "Declined",
        "Rejected",
    ],
    "Rework": [
        "Reopened",
        "Re-open",
        "Re open",
        "Changes Requested",
    ],
    "To Do": [
        "ToDo",
        "Open",
        "Backlog",
        "New",
    ],
    "In Progress": [
        "In Development",
        "Development",
        "Active",
        "Working",
    ],
    "Done": [
        "Closed",
        "Complete",
        "Completed",
        "Resolved",
    ],
}

# ── MCP server transport ─────────────────────────────────────────────────────
MCP_HOST = "127.0.0.1"
MCP_PORT = 8765
