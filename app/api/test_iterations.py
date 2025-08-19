# # 📁 app/api/test_iterations.py

# from fastapi import APIRouter, Query, Body
# from pydantic import BaseModel
# from typing import List, Optional
# from datetime import datetime, timedelta
# import pytz
# # from app.services.jira_services import get_jira_client


# # from app.utils.jira_utils import (
# #     get_all_projects,
# #     get_boards_for_project,
# #     get_assignees_for_project,
# #     generate_cfd_data,
# #     fetch_release_issues,
# #     fetch_fix_versions,
# #     fetch_components
# # )
# # from app.services.jira_services import process_issues
# # from app.services.openai_summary import summarize_issues_with_openai
# # from app.schemas.jira_models import JiraInput

# router = APIRouter()

# @router.get("/projects")
# def get_projects():
#     jira = get_jira_client()
#     return {"projects": get_all_projects(jira)}

# @router.get("/boards")
# def get_boards(project_key: str = Query(...)):
#     jira = get_jira_client()
#     return {"boards": get_boards_for_project(jira, project_key)}

# @router.get("/assignees")
# def get_assignees(project_key: str = Query(...)):
#     jira = get_jira_client()
#     return get_assignees_for_project(jira, project_key)

# @router.post("/fetch_jira_issues")
# def fetch_jira_issues(input: JiraInput):
#     jira = get_jira_client()
#     now = datetime.now(pytz.utc)
#     start_dt = datetime.strptime(input.start_date, "%Y-%m-%d").replace(tzinfo=pytz.utc) if input.start_date else now - timedelta(days=14)
#     end_dt = datetime.strptime(input.end_date, "%Y-%m-%d").replace(tzinfo=pytz.utc) if input.end_date else now

#     iteration_range = f"{start_dt.strftime('%d %b %Y')} - {end_dt.strftime('%d %b %Y')}"

#     project = next((p for p in jira.projects() if p.key == input.project_key), None)
#     boards = jira.boards(projectKeyOrID=project.key)
#     board = next((b for b in boards if str(b.id) == str(input.board_id)), None)

#     data, status_count, throughput, total_cycle_time, cycle_time_count, key_highlights_summary = process_issues(
#         jira, input.project_key, input.assignees, start_dt, end_dt
#     )
#     cfd_data = generate_cfd_data(jira, input.project_key, input.assignees, start_dt, end_dt)
#     avg_cycle_time = round(total_cycle_time / cycle_time_count, 2) if cycle_time_count else None

#     return {
#         "project": project.name,
#         "board": board.name if board else None,
#         "issues": data,
#         "cfd_data": cfd_data,
#         "metrics": {
#             "throughput": throughput,
#             "avg_cycle_time": avg_cycle_time
#         },
#         "key_highlights_summary": key_highlights_summary,
#         "date_range": iteration_range
#     }

# @router.get("/releases")
# def get_releases(project_key: str = Query(...), start_date: Optional[str] = Query(None), end_date: Optional[str] = Query(None)):
#     jira = get_jira_client()
#     now = datetime.now(pytz.utc)
#     start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=pytz.utc) if start_date else now - timedelta(days=14)
#     end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=pytz.utc) if end_date else now

#     versions = jira.project_versions(project_key)
#     releases = []
#     for v in versions:
#         if getattr(v, 'released', False) and getattr(v, 'releaseDate', None):
#             release_dt = datetime.strptime(v.releaseDate, "%Y-%m-%d").replace(tzinfo=pytz.utc)
#             if start_dt <= release_dt <= end_dt:
#                 releases.append({
#                     "name": v.name,
#                     "id": v.id,
#                     "description": getattr(v, 'description', ''),
#                     "releaseDate": v.releaseDate,
#                     "archived": getattr(v, 'archived', False),
#                     "released": v.released
#                 })

#     releases_with_issues = []
#     for rel in releases:
#         rel["issues"] = fetch_release_issues(jira, project_key, rel["name"], start_dt, end_dt)
#         releases_with_issues.append(rel)

#     return {"releases": releases_with_issues, "date_range": f"{start_dt.date()} - {end_dt.date()}"}

# @router.get("/fix_versions")
# def get_fix_versions(project_key: str = Query(...)):
#     jira = get_jira_client()
#     return {"fix_versions": fetch_fix_versions(jira, project_key)}

# @router.get("/components")
# def get_components(project_key: str = Query(...)):
#     jira = get_jira_client()
#     return {"components": fetch_components(jira, project_key)}

# @router.post("/epic_metrics")
# def get_epic_metrics(payload: dict = Body(...)):
#     project_key = payload.get("project_key")
#     fix_version = payload.get("fix_version")
#     components = payload.get("components", [])
#     issue_type = payload.get("issue_type", "Epic")

#     jira = get_jira_client()
#     if issue_type and not fix_version and not components:
#         jql = f'project = "{project_key}" AND issuetype = "{issue_type}"'
#     else:
#         jql = f'project = "{project_key}" AND issuetype = "{issue_type}"'
#         if fix_version:
#             jql += f' AND fixVersion = "{fix_version}"'
#         if components:
#             comp_jql = " OR ".join([f'component = "{c}"' for c in components])
#             jql += f' AND ({comp_jql})'

#     epics = jira.search_issues(jql, maxResults=100)
#     epic_metrics = []
#     for epic in epics:
#         epic_key = epic.key
#         epic_name = getattr(epic.fields, "summary", "")
#         epic_status = getattr(epic.fields.status, "name", "")

#         if issue_type.lower() == "epic":
#             jql_issues = f'"Epic Link" = "{epic_key}"'
#             if fix_version:
#                 jql_issues += f' AND fixVersion = "{fix_version}"'
#         else:
#             jql_issues = f'"Parent Link" = "{epic_key}"'
#             if fix_version:
#                 jql_issues += f' AND fixVersion = "{fix_version}"'
#         if components:
#             comp_jql = " OR ".join([f'component = "{c}"' for c in components])
#             jql_issues += f' AND ({comp_jql})'

#         issues = jira.search_issues(jql_issues, maxResults=500)
#         total_issues = len(issues)
#         done_issues = sum(1 for i in issues if getattr(i.fields.status, "name", "").lower() in ["done", "closed", "resolved", "cancelled", "deferred", 'completed', 'released', 'accepted', 'approved'])
#         inprogress_issues = sum(1 for i in issues if getattr(i.fields.status, "name", "").lower() in ["execution", "discovery", "realization", "in progress", "in review", "blocked", "pause", "dev complete", "in development", "in testing", "in qa"])
#         notstarted_issues = total_issues - done_issues - inprogress_issues
#         progress = round((done_issues / total_issues) * 100, 2) if total_issues else 0

#         epic_metrics.append({
#             "epic_key": epic_key,
#             "epic_name": epic_name,
#             "epic_status": epic_status,
#             "total_issues": total_issues,
#             "done_issues": done_issues,
#             "inprogress_issues": inprogress_issues,
#             "notstarted_issues": notstarted_issues,
#             "progress_percent": progress
#         })

#     return {"epics": epic_metrics}