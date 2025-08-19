# 📁 backend/app/utils/jira_utils.py
from datetime import datetime, timedelta
import pytz
from jira import JIRA
from app.config import settings



def get_jira_client():
    return JIRA(server=settings.jira_domain, basic_auth=(settings.jira_email, settings.jira_api_token))


def get_all_sprints(jira, board_id):
    """Fetch all sprints for a board by paginating through the JIRA API."""
    all_sprints = []
    start_at = 0
    max_results = 50
    while True:
        sprints = jira.sprints(board_id, startAt=start_at, maxResults=max_results, state="active,future,closed")
        sprints_list = list(sprints) if hasattr(sprints, '__iter__') else []
        if not sprints_list:
            break
        all_sprints.extend(sprints_list)
        if len(sprints_list) < max_results:
            break
        start_at += max_results
    return all_sprints

def fetch_velocity_and_say_do(jira, sprint, project_key, assignees):
    assignee_jql = " OR ".join([f'assignee = "{a}"' for a in assignees])
    jql = f'project = "{project_key}" AND Sprint = {sprint.id} AND ({assignee_jql})'
    issues = jira.search_issues(jql, maxResults=500)
    committed = 0
    completed = 0
    for issue in issues:
        sp = getattr(issue.fields, 'customfield_10008', None)
        sp = float(sp) if sp is not None else 0
        committed += sp
        status = issue.fields.status.name.lower()
        if status in ['done', 'closed', 'resolved', 'complete', 'completed', 'cancelled', 'deploy ready']:
            completed += sp
    say_do_ratio = round((completed / committed) * 100, 2) if committed else 0
    return {
        "committed": committed,
        "completed": completed,
        "say_do_ratio": say_do_ratio
    }

def generate_cfd_data(jira, project_key, assignees, start_date, end_date):
    cfd_data = []
    assignee_str = ', '.join(f'"{u}"' for u in assignees)
    print(f"Generating CFD data for project: {project_key}, assignees: {assignee_str}")
    days = (end_date - start_date).days
    for i in range(days, -1, -1):
        date = (start_date + timedelta(days=i)).strftime("%Y/%m/%d")
        jql_cfd = f'project = "{project_key}" AND updated >= "{date} 00:00" AND updated <= "{date} 23:59" AND assignee in ({assignee_str})'
        cfd_issues = jira.search_issues(jql_cfd, maxResults=500)
        status_counts = {}
        for issue in cfd_issues:
            status = issue.fields.status.name
            status_counts[status] = status_counts.get(status, 0) + 1
        for status, count in status_counts.items():
            cfd_data.append({
                "Date": date,
                "Status": status,
                "Issue Count": count
            })
    print(f"Generated CFD data points: {len(cfd_data)}")
    return cfd_data

from jira import JIRA

def get_assignees_from_jql(project_key, jira, assignees, start_at, max_results, jql):
    print(f"Final JQL: {jql}")
    while start_at <= 1000:
        # Pass JQL as the first positional argument (no jql= keyword)
        issues = jira.enhanced_search_issues(jql, params={"startAt": start_at, "maxResults": max_results})
        print(f"Fetched {len(issues)} issues starting at {start_at}")
        if not issues:
            break
        for issue in issues:
            if issue.fields.assignee and issue.fields.assignee.displayName:
                assignees.add(issue.fields.assignee.displayName)
        if len(issues) < max_results:
            break
        start_at += max_results

    print(f"Found {len(assignees)} unique assignees for project {project_key}")
    print("Assignees: ", sorted(list(assignees)))
    return {"assignees": sorted(list(assignees))} if assignees else {"assignees": []}
