# from jira import JIRA
# from datetime import datetime
# from app.config import settings


# def process_date_issues(jira, project_key, assignees, start_date, end_date):
#     data = []
#     throughput = 0
#     total_cycle_time = 0
#     cycle_time_count = 0
#     all_issues = []

#     for assignee in assignees:
#         jql_query = f'project = "{project_key}" AND assignee = "{assignee}" AND updated >= "{start_date.strftime('%Y-%m-%d')}" AND updated <= "{end_date.strftime('%Y-%m-%d')}"'
#         issues = jira.search_issues(jql_query, maxResults=500, expand="changelog")
#         all_issues.extend(issues)

#         for issue in issues:
#             issue_type = issue.fields.issuetype.name.lower()
#             if issue_type in ["epic", "initiative", "feature", "sub-task"]:
#                 continue
#             status = issue.fields.status.name
#             created = issue.fields.created
#             updated = issue.fields.updated
#             data.append({
#                 "Issue Type": issue.fields.issuetype.name,
#                 "Issue Key": issue.key,
#                 "Summary": issue.fields.summary,
#                 "Assignee": assignee,
#                 "Status": status,
#                 "Created Date": created,
#                 "Updated Date": updated,
#                 "Priority": issue.fields.priority.name if issue.fields.priority else "None",
#                 "Component": ", ".join([c.name for c in issue.fields.components])
#             })
#             if status.lower() in ['done', 'closed', 'cancelled']:
#                 throughput += 1
#             try:
#                 dt_start = datetime.strptime(created[:19], "%Y-%m-%dT%H:%M:%S")
#                 dt_end = datetime.strptime(updated[:19], "%Y-%m-%dT%H:%M:%S")
#                 total_cycle_time += abs((dt_end - dt_start).days)
#                 cycle_time_count += 1
#             except:
#                 pass

#     return data, all_issues, throughput, total_cycle_time, cycle_time_count

