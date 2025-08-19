# 📁 app/api/sprint_report.py

from fastapi import APIRouter, Query, Body
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta
from app.schemas.jira_models import JiraInput
from app.utils.jira_utils import (get_jira_client)
from app.utils import jira_utils
from app.utils import openai_utils
from app.config import settings

router = APIRouter()

class JiraInput(BaseModel):
    project_key: str
    board_id: str
    assignees: List[str]
    sprint_id: Optional[str] = None  # Added for sprint-based queries
    start_date: Optional[str] = None  # YYYY-MM-DD
    end_date: Optional[str] = None    # YYYY-MM-DD

@router.get("/projects")
def get_projects():
    jira = get_jira_client()
    print("Fetching projects from JIRA...")
    projects = [{"key": p.key, "name": p.name} for p in jira.projects()]
    print(f"Found {len(projects)} projects")
    return {"projects": sorted(projects, key=lambda x: x["name"])}

@router.get("/boards")
def get_boards(project_key: str = Query(...)):
    jira = get_jira_client()
    print(f"Fetching boards for project: {project_key}")
    boards = jira.boards(projectKeyOrID=project_key)
    # Defensive: ensure boards is a list
    scrum_boards = [{"id": b.id, "name": b.name} for b in boards if getattr(b, "type", None) == "scrum"]
    print(f"Found {len(scrum_boards)} boards for project {project_key}")
    return {"boards": sorted(scrum_boards, key=lambda x: x["name"])}

@router.get("/assignees")
def get_assignees(project_key: str = Query(...), board_id: str = Query(None)):
    """
    Return all unique assignees who have issues in the selected project (and board, if provided).
    """
    print(f"Fetching unique assignees for project: {project_key}, board: {board_id if board_id else 'N/A'}")

    jira = get_jira_client()
    assignees = set()
    start_at = 0
    max_results = 100

    # Build JQL for project (and board if provided)
    jql = f'project = "{project_key}"'
    print(f"Initial JQL: {jql}")

    if board_id:
        # Get all sprints for the board
        sprints = jira_utils.get_all_sprints(jira, board_id)
        sprint_ids = [str(s.id) for s in sprints]
        sprint_ids = sorted(sprint_ids, key=lambda x: int(x), reverse=True)  # Sort sprint IDs numerically
        print(f"Found {len(sprint_ids)} sprints for board {board_id}: {sprint_ids}")
        if sprint_ids:
            jql += f' AND Sprint in ({",".join(sprint_ids)})'

    return jira_utils.get_assignees_from_jql(project_key, jira, assignees, start_at, max_results, jql)

@router.get("/sprints")
def get_sprints(board_id: str = Query(...)):
    """
    Returns all sprints for a board, sorted by startDate descending.
    """
    jira = get_jira_client()
    print(f"Fetching sprints for board ID: {board_id}")
    sprints_list = jira_utils.get_all_sprints(jira, board_id)
    print(f"Total sprints fetched: {len(sprints_list)}")
    print("Sprints:", [s.name for s in sprints_list])
    # Sort: active first, then by startDate descending
    def sprint_sort_key(s):
        state = getattr(s, "state", "").lower()
        start = getattr(s, "startDate", None)
        try:
            ts = int(datetime.strptime(start, "%Y-%m-%dT%H:%M:%S.%f%z").timestamp()) if start else 0
        except Exception:
            ts = 0
        return (0 if state == "active" else 1, -ts)
    sprints_sorted = sorted(sprints_list, key=sprint_sort_key)
    return {
        "sprints": [
            {
                "id": s.id,
                "name": s.name,
                "state": getattr(s, "state", ""),
                "startDate": getattr(s, "startDate", None),
                "endDate": getattr(s, "endDate", None)
            }
            for s in sprints_sorted
        ]
    }

@router.post("/fetch_jira_issues")
def fetch_jira_issues(input: JiraInput):
    try:
        jira = get_jira_client()
        print(f"Connected to JIRA: {JIRA_DOMAIN}")
        project = next((p for p in jira.projects() if p.key == input.project_key), None)
        print(f"Fetching issues for project: {input.project_key}, sprint: {input.sprint_id if input.sprint_id else 'N/A'}")
        boards = jira.boards(projectKeyOrID=project.key)
        print(f"Found {len(boards)} boards for project {project.key}")
        board = next((b for b in boards if str(b.id) == str(input.board_id)), None)

        sprints = jira_utils.get_all_sprints(jira, board.id)
        if not sprints:
            return {"error": "No sprint found for this board."}
        print(f"Found {len(sprints)} sprints for board {board.id}")
        
        sprint = next((s for s in sprints if str(s.id) == str(input.sprint_id)), None)
        sprint_start = datetime.strptime(sprint.startDate[:19], DATETIME_FORMAT)
        sprint_end = datetime.strptime(sprint.endDate[:19], DATETIME_FORMAT)
        iteration_range = f"{sprint_start.strftime('%d %b %Y')} - {sprint_end.strftime('%d %b %Y')}"
        
        print(f"Fetching issues for project: {project.key}, board: {board.name if board else 'N/A'}, "
              f"assignees: {input.assignees}, date range: {iteration_range}")

        data, _, throughput, total_cycle_time, cycle_time_count, key_highlights_summary = process_issues(
            jira, input.project_key, input.assignees, sprint.id
        )
        cfd_data = jira_utils.generate_cfd_data(jira, input.project_key, input.assignees, sprint_start, sprint_end)
        print(f"CFD data points: {len(cfd_data)}")
        # Fetch velocity and say/do ratio
        print(f"Calculating velocity and say/do ratio for sprint {sprint.name}...")
        velocity = jira_utils.fetch_velocity_and_say_do(jira, sprint, project.key, input.assignees)
        avg_cycle_time = round(total_cycle_time / cycle_time_count, 2) if cycle_time_count else None
        print(f"Total issues processed: {len(data)}, Throughput: {throughput}, "
              f"Average Cycle Time: {avg_cycle_time}, CFD Data Points: {len(cfd_data)}")
        return {
            "project": input.project_key,
            "board": input.board_id,
            "issues": data,
            "cfd_data": cfd_data,
            "metrics": {
                "throughput": throughput,
                "avg_cycle_time": avg_cycle_time,
                "velocity": velocity
            },
            "date_range": iteration_range,
            "key_highlights_summary": key_highlights_summary,
            "from_cache": False
        }
    except Exception as e:
        return {
            "project": input.project_key,
            "board": input.board_id,
            "issues": [],
            "cfd_data": [],
            "metrics": {},
            "date_range": "",
            "from_cache": True,
            "error": str(e)
        }

@router.get("/releases")
def get_releases(
    project_key: str = Query(...),
    since_date: str = Query(...),
    until_date: str = Query(...)
):
    """
    Fetch all releases (fix-versions) for a project with status 'released' in the last 14 days or in the given date range.
    Returns release details and associated issues for each release.
    """
    jira = get_jira_client()
    now = datetime.now(pytz.utc)
    print(f"Fetching releases for project: {project_key}, date range: {since_date} - {until_date}")
    if since_date and until_date:
        start_dt = datetime.strptime(since_date, "%Y-%m-%d").replace(tzinfo=pytz.utc)
        end_dt = datetime.strptime(until_date, "%Y-%m-%d").replace(tzinfo=pytz.utc)
    else:
        end_dt = now
        start_dt = now - timedelta(days=14)

    # Fetch all versions for the project
    versions = jira.project_versions(project_key)
    releases = []
    for v in versions:
        if getattr(v, 'released', False) and getattr(v, 'releaseDate', None):
            try:
                release_dt = datetime.strptime(v.releaseDate, "%Y-%m-%d").replace(tzinfo=pytz.utc)
            except Exception:
                continue
            if start_dt <= release_dt <= end_dt:
                releases.append({
                    "name": v.name,
                    "id": v.id,
                    "description": getattr(v, 'description', ''),
                    "releaseDate": v.releaseDate,
                    "archived": getattr(v, 'archived', False),
                    "released": v.released
                })

    # --- Sort releases by releaseDate ascending ---
    releases.sort(key=lambda r: r["releaseDate"])
    
    # For each release, fetch associated issues using helper
    releases_with_issues = []
    print(f"Found {len(releases)} releases in the date range {start_dt.date()} - {end_dt.date()}")
    for rel in releases:
        rel["issues"] = fetch_release_issues(jira, project_key, rel["name"], start_dt, end_dt)
        releases_with_issues.append(rel)
    print(f"Processed {len(releases_with_issues)} releases with issues")
    return {"releases": releases_with_issues, "date_range": f"{start_dt.date()} - {end_dt.date()}"}

@router.get("/fix_versions")
def get_fix_versions(project_key: str = Query(...)):
    """
    Returns all fix versions for a project (for Epic Metrics dropdown).
    """
    jira = get_jira_client()
    versions = jira.project_versions(project_key)
    return {
        "fix_versions": [
            {"id": v.id, "name": v.name, "released": getattr(v, "released", False)}
            for v in versions
        ]
    }

@router.get("/components")
def get_components(project_key: str = Query(...)):
    """
    Returns all components for a project (for Epic Metrics dropdown).
    """
    jira = get_jira_client()
    project = jira.project(project_key)
    return {
        "components": [
            {"id": c.id, "name": c.name}
            for c in getattr(project, "components", [])
        ]
    }

@router.post("/epic_metrics")
def get_epic_metrics(
    payload: dict = Body(...)
):
    """
    Returns metrics for a given project, fix version, and optional components and issue type.
    If only issue_type is selected (no fix_version/components), return all issues of that type for the project.
    """
    project_key = payload.get("project_key")
    fix_version = payload.get("fix_version")
    components = payload.get("components", [])  # List of component names or empty
    issue_type = payload.get("issue_type", "Epic")  # Epic, Feature, Initiative

    jira = get_jira_client()

    # If only issue_type is selected (no fix_version/components), fetch all issues of that type for the project
    if issue_type and not fix_version and not components:
        jql = f'project = "{project_key}" AND issuetype = "{issue_type}"'
    else:
        jql = f'project = "{project_key}" AND issuetype = "{issue_type}"'
        if fix_version:
            jql += f' AND fixVersion = "{fix_version}"'
        if components:
            comp_jql = " OR ".join([f'component = "{c}"' for c in components])
            jql += f' AND ({comp_jql})'

    epics = jira.search_issues(jql, maxResults=100)
    epic_metrics = []
    for epic in epics:
        epic_key = epic.key
        epic_name = getattr(epic.fields, "summary", "")
        epic_status = getattr(epic.fields.status, "name", "")
        # Find all issues linked to this epic/feature/initiative and fix version (and components if provided)
        # For Epic: "Epic Link", for Feature/Initiative: "Parent Link"
        if issue_type.lower() == "epic":
            jql_issues = f'"Epic Link" = "{epic_key}"'
            if fix_version:
                jql_issues += f' AND fixVersion = "{fix_version}"'
        else:
            jql_issues = f'"Parent Link" = "{epic_key}"'
            if fix_version:
                jql_issues += f' AND fixVersion = "{fix_version}"'
        if components:
            comp_jql = " OR ".join([f'component = "{c}"' for c in components])
            jql_issues += f' AND ({comp_jql})'
        issues = jira.search_issues(jql_issues, maxResults=500)
        total_issues = len(issues)
        done_issues = sum(
            1 for i in issues if getattr(i.fields.status, "name", "").lower() in ["done", "closed", "resolved", "cancelled", "deferred", 'completed', 'released', 'accepted', 'approved']
        )
        inprogress_issues = sum(
            1 for i in issues if getattr(i.fields.status, "name", "").lower() in ["execution", "discovery", "realization", "in progress", "in review", "blocked", "pause", "dev complete", "in development", "in testing", "in qa"]
        )
        notstarted_issues = total_issues - done_issues - inprogress_issues
        progress = round((done_issues / total_issues) * 100, 2) if total_issues else 0
        epic_metrics.append({
            "epic_key": epic_key,
            "epic_name": epic_name,
            "epic_status": epic_status,
            "total_issues": total_issues,
            "done_issues": done_issues,
            "inprogress_issues": inprogress_issues,
            "notstarted_issues": notstarted_issues,
            "progress_percent": progress
        })
    return {"epics": epic_metrics}

def process_issues(jira, project_key, assignees, sprint_id):
    data = []
    status_count = {}
    throughput = 0
    total_cycle_time = 0
    cycle_time_count = 0
    print(f"Fetching issues for project: {project_key}, assignees: {assignees}, sprint_id: {sprint_id}")

    for assignee in assignees:
        jql_query = (
            f'project = "{project_key}" AND assignee = "{assignee}" '
            f'AND Sprint = {sprint_id}'
        )
        print(f"JQL Query for assignee {assignee}: {jql_query}")
        issues = jira.search_issues(jql_query, maxResults=500, expand="changelog,comment")
        print(f"Total issues fetched for assignee {assignee}: {len(issues)}")

        for issue in issues:
            issue_type = issue.fields.issuetype.name.lower()
            # Exclude Epic, Feature, Initiative, Sub-task from throughput and metrics
            if issue_type in ["epic", "initiative", "feature", "sub-task"]:
                continue

            # Sort comments by created date (ascending)
            comments_list = []
            if hasattr(issue.fields, "comment") and hasattr(issue.fields.comment, "comments"):
                comments_objs = issue.fields.comment.comments
                comments_list = sorted(
                    [
                        {
                            "body": c.body,
                            "created": c.created
                        }
                        for c in comments_objs
                    ],
                    key=lambda x: x["created"]
                )
            # Format comments as list of dicts (not as a string)
            status = issue.fields.status.name
            created = issue.fields.created
            updated = issue.fields.updated
            story_points = getattr(issue.fields, 'customfield_10008', None)
            data.append({
                "Issue Type": issue.fields.issuetype.name,
                "Issue Key": issue.key,
                "Summary": issue.fields.summary,
                "Assignee": assignee,
                "Status": status,
                "Created Date": created,
                "Updated Date": updated,
                #"Story Points": story_points,
                "Priority": issue.fields.priority.name if issue.fields.priority else "None",
                "Component": ", ".join([c.name for c in issue.fields.components])
                #"Comments": comments_list  # Now a list of dicts
            })

            # Metrics
            # --- Throughput: Only count Done, Closed, Cancelled (not Resolved) ---
            if status and status.lower() in ['done', 'closed', 'cancelled', 'deploy ready', 'completed', 'resolved', 'released', 'accepted', 'approved']:
                throughput += 1

            # --- Modified Cycle Time Calculation: To Do -> Done/Closed/Cancelled ---
            cycle_start = None
            cycle_end = None
            done_statuses = ['done', 'closed', 'cancelled', 'resolved', 'deploy ready', 'completed', 'released', 'accepted', 'approved']
            todo_statuses = ['to do', 'todo', 'new', 'open', 'ready for dev', 'ready for work', 'ready for development', 'ready', 'sprint ready']
            if hasattr(issue, "changelog"):
                for history in sorted(issue.changelog.histories, key=lambda h: h.created):
                    for item in history.items:
                        if item.field.lower() == "status":
                            to_status = (item.toString or "").strip().lower()
                            hist_dt = datetime.strptime(history.created[:19], "%Y-%m-%dT%H:%M:%S")
                            # Find first transition to To Do (or Todo)
                            if to_status in todo_statuses and cycle_start is None:
                                cycle_start = hist_dt
                            # Find first transition to Done/Closed/Cancelled/Resolved after To Do
                            if cycle_start is not None and to_status in done_statuses and cycle_end is None:
                                cycle_end = hist_dt
                    if cycle_start is not None and cycle_end is not None:
                        break
            # If not found in changelog, fallback to created/updated
            if cycle_start and cycle_end and cycle_end > cycle_start:
                total_cycle_time += abs((cycle_end - cycle_start).days)
                cycle_time_count += 1
            elif created and updated:
                # fallback (legacy)
                created_dt = datetime.strptime(created[:19], "%Y-%m-%dT%H:%M:%S")
                updated_dt = datetime.strptime(updated[:19], "%Y-%m-%dT%H:%M:%S")
                total_cycle_time += abs((updated_dt - created_dt).days)
                cycle_time_count += 1
            status_count[status] = status_count.get(status, 0) + 1
    key_highlights_summary = openai_utils.summarize_issues_with_openai(issues, settings.openai_api_key)
    return data, status_count, throughput, total_cycle_time, cycle_time_count, key_highlights_summary

def fetch_release_issues(jira, project_key, release_name, start_date=None, end_date=None):
    """Helper to fetch issues for a given release name, filtered by date range if provided."""
    jql = f'project = "{project_key}" AND fixVersion = "{release_name}"'
    if start_date and end_date:
        jql += f' AND updated >= "{start_date.strftime("%Y/%m/%d")}" AND updated <= "{end_date.strftime("%Y/%m/%d")}"'
    issues = jira.search_issues(jql, maxResults=500, expand="changelog,comment")
    issue_data = []
    print(f"Fetching issues for release: {release_name}, total issues: {len(issues)}, date range: {start_date} - {end_date if end_date else 'N/A'}")
    for issue in issues:
        issue_type = issue.fields.issuetype.name.lower()
        if issue_type in ["epic", "initiative", "feature"]:
            continue
        # Sort comments by created date (ascending)
        comments_list = []
        if hasattr(issue.fields, "comment") and hasattr(issue.fields.comment, "comments"):
            comments_objs = issue.fields.comment.comments
            comments_list = sorted(
                [
                    {
                        "body": c.body,
                        "created": c.created
                    }
                    for c in comments_objs
                ],
                key=lambda x: x["created"]
            )
        story_points = getattr(issue.fields, 'customfield_10016', None)
        issue_data.append({
            "Issue Type": issue.fields.issuetype.name,
            "Issue Key": issue.key,
            "Summary": issue.fields.summary,
            "Assignee": issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned",
            "Status": issue.fields.status.name,
            "Created Date": issue.fields.created,
            "Updated Date": issue.fields.updated,
            #"Story Points": story_points,
            "Priority": issue.fields.priority.name if issue.fields.priority else "None"
            #"Comments": comments_list  # Now a list of dicts
        })
    print(f"Processed issues for release: {release_name}, total issues: {len(issue_data)}")
    return issue_data