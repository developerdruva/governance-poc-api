import openai
import json
from datetime import datetime, timedelta
from jira import JIRA
import pytz
import re
import tiktoken


def _create_example_output():
    """Helper function to provide example output format for OpenAI prompt."""
    return '''
EXAMPLE OUTPUT:
{
  "completed_actions": [
    "Completed user authentication and authorization system with OAuth2 integration (USER-123)",
    "Delivered API endpoints for customer management with full CRUD operations",
    "Fixed critical performance issues in database queries (resolved 3 related high-priority tickets)",
    "Deployed notification service to production environment with monitoring"
  ],
  "inprogress_actions": [
    "⚠️ CRITICAL: Developing payment processing integration with Stripe API (PAY-456 - High Priority)",
    "Implementing real-time dashboard analytics and reporting features", 
    "Refactoring legacy code modules for better maintainability and performance",
    "Testing mobile app compatibility across iOS and Android platforms (regression testing)"
  ],
  "upcoming_actions": [
    "Design and implement advanced search functionality with filtering capabilities",
    "Set up automated backup and disaster recovery procedures",
    "Plan migration to new cloud infrastructure platform (AWS)",
    "Research and evaluate third-party integration options for analytics"
  ],
  "risks_identified": [
    "🚫 CRITICAL BLOCKER: Payment gateway integration blocked due to vendor API changes - blocks release (PAY-456)",
    "⚠️ HIGH PRIORITY: Database performance degrading under high load - needs immediate attention (DB-789)",
    "Third-party service dependency causing intermittent failures during peak hours",
    "Security vulnerability discovered in authentication module - requires urgent patch (SEC-101)"
  ]
}'''


def _create_openai_prompt():
    """Create the core prompt for OpenAI analysis."""
    return """You are an expert project manager analyzing JIRA issues for a project status report. You must include ALL issues in your analysis and categorize them accurately.

CRITICAL COUNTING REQUIREMENT:
- YOU MUST MAINTAIN A 1:1 MAPPING BETWEEN INPUT ISSUES AND OUTPUT ITEMS
- If you receive 4 completed issues, you MUST produce exactly 4 items in completed_actions
- If you receive 3 in-progress issues, you MUST produce exactly 3 items in inprogress_actions
- NEVER group multiple issues into a single summary item
- Each issue must have its own dedicated line item in the output

    
STRICT CLASSIFICATION RULES:
1. **completed_actions**: Issues with status containing [Done, Closed, Complete, Completed, Cancelled, Deploy Ready, Resolved, Fixed, Delivered, Merged, Deployed, Released, Verified, Accepted, Finished, Implemented] - INCLUDE ALL OF THESE INDIVIDUALLY
2. **inprogress_actions**: Issues with status containing [In Progress, In Development, In Review, Testing, QA, Code Review, In Testing, Development, Implementing, Coding, Under Review, Pending Review, Ready for Testing, Ready for QA, In QA, Review, Active, Working, Development Complete, Dev Complete] - INCLUDE ALL OF THESE INDIVIDUALLY
3. **upcoming_actions**: Issues with status [To Do, Ready, Sprint Ready, New, Open, Created, Planned, Backlog] - INCLUDE ALL OF THESE INDIVIDUALLY
4. **risks_identified**: Issues that are blocked, paused, have risk indicators, high priority problems, or dependency issues - BUT NEVER COMPLETED ISSUES - INCLUDE ALL OF THESE INDIVIDUALLY

MANDATORY REQUIREMENTS:
- YOU MUST INCLUDE EVERY SINGLE ISSUE in one of the four categories
- COUNT the issues you receive and ensure your output accounts for ALL of them with individual entries
- NEVER consolidate multiple issues into a single summary line
- Each issue gets its own dedicated summary entry with its JIRA key
- Look for the category hints in square brackets [✅ COMPLETED | ⚠️ CRITICAL PRIORITY] to guide classification
- Pay attention to the "→ CATEGORY:" guidance provided for each issue
- NEVER exclude issues - if unsure, use the status as the primary classifier

CRITICAL EXCLUSION RULE:
- Issues marked with "✅ COMPLETED" must NEVER appear in risks_identified, regardless of priority or other factors
- Completed work cannot be a risk since it's already done

ENHANCED OUTPUT REQUIREMENTS:
- Each issue must have its own individual entry in the appropriate category
- Include JIRA keys (e.g., ABC-123) in each individual summary
- Use action-oriented, business-friendly language for each individual item
- DO NOT group similar issues - maintain individual visibility for ALL issues
- Each line item should reference exactly one JIRA issue

OUTPUT FORMAT: Return a JSON object with arrays of strings. Each string represents exactly one JIRA issue. Ensure 1:1 mapping between input issues and output items."""


def _extract_issue_context(issue):
    """Extract relevant context from a JIRA issue for analysis."""
    summary = issue.fields.summary
    status = issue.fields.status.name
    priority = issue.fields.priority.name if issue.fields.priority else "No Priority"
    issue_type = issue.fields.issuetype.name.lower()
    
    # Get additional context fields
    labels = [label for label in (issue.fields.labels or [])]
    components = [comp.name for comp in (issue.fields.components or [])]
    description = getattr(issue.fields, 'description', '') or ''
    
    # Get first 200 chars of description to avoid token limits
    description = description[:200] + '...' if len(description) > 200 else description
    
    # Check for flags/blockers
    is_flagged = getattr(issue.fields, 'flagged', False) or any('flag' in str(label).lower() for label in labels)
    
     # Expanded completed status list
    completed_statuses = [
        'done', 'closed', 'complete', 'completed', 'cancelled', 'deploy ready', 
        'resolved', 'fixed', 'delivered', 'merged', 'deployed', 'released',
        'verified', 'accepted', 'finished', 'implemented', 'ready to deploy'
    ]
    
    # Expanded in-progress status list
    inprogress_statuses = [
        'in progress', 'in development', 'in review', 'testing', 'qa', 
        'code review', 'in testing', 'development', 'implementing', 
        'coding', 'under review', 'pending review', 'ready for testing', 'qa complete', 'qa ready',
        'ready for qa', 'in qa', 'review', 'active', 'working', 'development complete', 'cab request submitted', 'dev complete'
    ]
    
    # Expanded blocked/risk status list
    blocked_statuses = [
        'blocked', 'pause', 'hold', 'on hold', 'waiting', 'impediment', 
        'stalled', 'blocker', 'suspended', 'paused', 'waiting for', 
        'dependency', 'external dependency'
    ]
    status_lower = status.lower() if status else ''

    # Enhanced priority and risk assessment
    is_critical_priority = priority.lower() in ['critical', 'highest', 'high', 'urgent', 'major', 'blocker']
    is_blocked = any(blocked_status in status_lower for blocked_status in blocked_statuses)
    is_completed = any(completed_status in status_lower for completed_status in completed_statuses)
    is_inprogress = any(inprogress_status in status_lower for inprogress_status in inprogress_statuses)
    
    has_risk_indicators = any(
        keyword in ' '.join(labels + components + [description, summary]).lower() 
        for keyword in ['risk', 'blocker', 'blocked', 'dependency', 'critical', 'urgent', 'escalation', 
                       'security', 'vulnerability', 'issue', 'problem', 'bug', 'defect', 'failure']
    )
    
    # Calculate issue age (if created date is available)
    issue_age_days = None
    if hasattr(issue.fields, 'created') and issue.fields.created:
        try:
            created_date = datetime.strptime(issue.fields.created[:19], "%Y-%m-%dT%H:%M:%S")
            issue_age_days = (datetime.now() - created_date).days
        except Exception:
            pass
    
            issue_age_days = (datetime.now() - created_date).days
        except Exception:
            pass
    
    return {
        'summary': summary,
        'status': status,
        'priority': priority,
        'issue_type': issue_type,
        'labels': labels,
        'components': components,
        'description': description,
        'is_flagged': is_flagged,
        'is_critical_priority': is_critical_priority,
        'is_blocked': is_blocked,
        'is_completed': is_completed,
        'is_inprogress': is_inprogress,
        'has_risk_indicators': has_risk_indicators,
        'issue_age_days': issue_age_days,
        'key': getattr(issue, 'key', 'Unknown')
    }


def _should_include_issue(issue_type):
    """Determine if an issue type should be included in the analysis."""
    return issue_type not in ["epic", "initiative", "feature", "sub-task"]


def _format_issue_for_analysis(issue_context):
    """Format an issue's context into a readable string for OpenAI analysis."""
    context_lines = []

    # Determine primary category based on status and priority
    category_hints = []

    if issue_context['is_completed']:
        category_hints.append("✅ COMPLETED")
    elif issue_context['is_blocked']:
        category_hints.append("🚫 BLOCKED")
    elif issue_context['is_inprogress']:
        category_hints.append("🔄 IN-PROGRESS")
    else:
        category_hints.append("📋 UPCOMING")
    
    if issue_context['is_critical_priority']:
        category_hints.append("⚠️ CRITICAL PRIORITY")
    
    if issue_context['has_risk_indicators'] and not issue_context['is_completed']:
        category_hints.append("⚡ RISK")

    # Create clear category guidance
    category_guidance = f" [{' | '.join(category_hints)}]"
    
    context_lines.append(f"- Summary: {issue_context['summary']}{category_guidance}")
    context_lines.append(f"  Key: {issue_context['key']}")
    context_lines.append(f"  Status: {issue_context['status']}")
    context_lines.append(f"  Priority: {issue_context['priority']}")
    context_lines.append(f"  Type: {issue_context['issue_type']}")

     # Add explicit categorization guidance
    if issue_context['is_completed']:
        context_lines.append("  → CATEGORY: completed_actions (Status indicates work is finished)")
    elif issue_context['is_blocked']:
        context_lines.append("  → CATEGORY: risks_identified (Issue is blocked and poses risk)")
    elif issue_context['is_inprogress']:
        context_lines.append("  → CATEGORY: inprogress_actions (Work is currently active)")
    else:
        context_lines.append("  → CATEGORY: upcoming_actions (Work is planned but not started)")
        
    if issue_context['labels']:
        context_lines.append(f"  Labels: {', '.join(issue_context['labels'])}")
    if issue_context['components']:
        context_lines.append(f"  Components: {', '.join(issue_context['components'])}")
    if issue_context['is_flagged']:
        context_lines.append("  Flagged: Yes")
    if issue_context['issue_age_days'] is not None:
        context_lines.append(f"  Age: {issue_context['issue_age_days']} days")
    if issue_context['description'] and issue_context['description'].strip():
        context_lines.append(f"  Description: {issue_context['description']}")
        
    return '\n'.join(context_lines)


def _prepare_issues_for_analysis(issues):
    """Prepare and filter issues for OpenAI analysis."""
    filtered_issues = []

    total_issues = len(issues)
    print(f"Total issues to analyze: {total_issues}")
    complexity_factors = {
        'critical_priority': 0,
        'blocked_issues': 0,
        'risk_indicators': 0,
        'flagged_issues': 0,
        'long_descriptions': 0,
        'multiple_components': 0,
        'old_issues': 0,
        'diverse_statuses': set(),
        'diverse_priorities': set(),
        'diverse_types': set()
    }

    for issue in issues:
        issue_context = _extract_issue_context(issue)
        print("Filtering issue: ", issue_context['summary'], " with issue type: ", issue_context['issue_type'])
         # Exclude Epic, Feature, Initiative, Sub-task from analysis
        if _should_include_issue(issue_context['issue_type']):
            filtered_issues.append(issue_context)

             # High-impact factors
            if issue_context['is_critical_priority']:
                complexity_factors['critical_priority'] += 1
            if issue_context['is_blocked']:
                complexity_factors['blocked_issues'] += 1
            if issue_context['has_risk_indicators']:
                complexity_factors['risk_indicators'] += 1
            if issue_context['is_flagged']:
                complexity_factors['flagged_issues'] += 1
                
            # Content complexity factors
            if len(issue_context['description']) > 100:
                complexity_factors['long_descriptions'] += 1
            if len(issue_context['components']) > 1:
                complexity_factors['multiple_components'] += 1
                
            # Age complexity
            if issue_context['issue_age_days'] and issue_context['issue_age_days'] > 30:
                complexity_factors['old_issues'] += 1
            
            # Diversity factors
            complexity_factors['diverse_statuses'].add(issue_context['status'])
            complexity_factors['diverse_priorities'].add(issue_context['priority'])
            complexity_factors['diverse_types'].add(issue_context['issue_type'])

        
    print("length of filtered issues:", len(filtered_issues))

    # Calculate weighted complexity score (0.0 to 1.0)
    score = 0.0
    
    # High-priority issues increase complexity significantly
    score += (complexity_factors['critical_priority'] / total_issues) * 0.3
    score += (complexity_factors['blocked_issues'] / total_issues) * 0.25
    score += (complexity_factors['risk_indicators'] / total_issues) * 0.2
    score += (complexity_factors['flagged_issues'] / total_issues) * 0.15
    
    # Content and age complexity
    score += (complexity_factors['long_descriptions'] / total_issues) * 0.1
    score += (complexity_factors['multiple_components'] / total_issues) * 0.05
    score += (complexity_factors['old_issues'] / total_issues) * 0.1
    
    # Diversity adds complexity (more statuses/priorities = harder to categorize)
    status_diversity = min(len(complexity_factors['diverse_statuses']) / 10, 1.0) * 0.15
    priority_diversity = min(len(complexity_factors['diverse_priorities']) / 5, 1.0) * 0.1
    type_diversity = min(len(complexity_factors['diverse_types']) / 8, 1.0) * 0.1
    
    score += status_diversity + priority_diversity + type_diversity
    
    # Volume factor (more issues = more complex)
    volume_factor = min(total_issues / 100, 1.0) * 0.2
    score += volume_factor
    
    # Ensure score stays within 0.0 to 1.0 range
    final_score = min(score, 1.0)
    
    print(f"Complexity analysis:")
    print(f"  - Total issues: {total_issues}")
    print(f"  - Critical priority: {complexity_factors['critical_priority']}")
    print(f"  - Blocked issues: {complexity_factors['blocked_issues']}")
    print(f"  - Risk indicators: {complexity_factors['risk_indicators']}")
    print(f"  - Status diversity: {len(complexity_factors['diverse_statuses'])}")
    print(f"  - Priority diversity: {len(complexity_factors['diverse_priorities'])}")
    print(f"  - Final complexity score: {final_score:.3f}")
    
    # # Sort issues to prioritize critical items (critical priority first, then blocked, then by age)
    # def priority_sort_key(issue_ctx):
    #     priority_score = 0
    #     if issue_ctx['is_critical_priority']:
    #         priority_score += 1000
    #     if issue_ctx['is_blocked']:
    #         priority_score += 500
    #     if issue_ctx['has_risk_indicators']:
    #         priority_score += 100
    #     if issue_ctx['is_flagged']:
    #         priority_score += 50
    #     # Add age factor (older issues get higher priority)
    #     if issue_ctx['issue_age_days']:
    #         priority_score += min(issue_ctx['issue_age_days'], 100)
    #     return -priority_score  # Negative for descending sort
    
    # filtered_issues.sort(key=priority_sort_key)
    
    # Format issues for analysis
    issue_lines = []
    for issue_context in filtered_issues:
        formatted_issue = _format_issue_for_analysis(issue_context)
        issue_lines.append(formatted_issue)
    
    return issue_lines, final_score


def _call_openai_api(full_prompt, openai_api_key, issue_count, complexity_score):
    """Make the actual OpenAI API call."""
    openai.api_key = openai_api_key

     # Always use maximum tokens for comprehensive output
    max_tokens = 4096
    model = "gpt-4o"  # Use best model for accuracy
    

    # # Choose model based on complexity
    # model = _get_optimal_model(issue_count, complexity_score)
    
    # # Adjust max_tokens based on complexity
    # if complexity_score > 0.8:
    #     max_tokens = 4096  # Maximum for complex analysis
    # elif complexity_score > 0.5:
    #     max_tokens = 3000  # Balanced
    # else:
    #     max_tokens = 2000  # Simpler analysis
    
    print(f"Using model: {model} with max_tokens: {max_tokens} (complexity: {complexity_score:.3f})")
    # Before API call:
    prompt_tokens = estimate_tokens(full_prompt)
    print(f"Estimated prompt tokens: {prompt_tokens}")

    try:
        response = openai.ChatCompletion.create(
            model=model,  # Use the determined model
            messages=[
                {
                    "role": "system", 
                    "content": """You are an expert project manager and JIRA analyst. Your primary responsibility is to ensure NO ISSUES ARE MISSED in your analysis. You must include every single issue provided in your categorization. Missing issues is considered a critical failure."""
                },
                {"role": "user", "content": full_prompt}
            ],
            temperature=0.1,      # Keep low for consistency
            top_p=0.9,           # Slightly higher for more diverse responses
            max_tokens=max_tokens,
            response_format={"type": "json_object"},  # Ensures JSON output
        )
        print("OpenAI response received successfully")
        return response
    except Exception as e:
        print("OpenAI API error:", e)
        return None

def _get_optimal_model(issue_count, complexity_score):
    """Choose model based on analysis complexity."""
    if issue_count > 100 or complexity_score > 0.8:
        return "gpt-4o"  # Complex analysis
    elif issue_count > 50:
        return "gpt-4o-mini"  # Good balance
    else:
        return "gpt-4o-mini"  # Cost-effective for smaller datasets

def estimate_tokens(text):
    encoding = tiktoken.encoding_for_model("gpt-4o")
    return len(encoding.encode(text))

def _parse_openai_response(response):
    """Parse and validate the OpenAI response."""
    # Default empty result
    default_result = {
        "completed_actions": [],
        "inprogress_actions": [],
        "upcoming_actions": [],
        "risks_identified": []
    }
    
    if not response or not response.choices or not response.choices[0].message:
        print("No valid response from OpenAI")
        return default_result
    
    content = response.choices[0].message.content.strip()
    print(f"Raw OpenAI response: {content}")
    
    # Clean up the response content
    if content.startswith("```"):
        # Remove all ```json ... ``` or ``` ... ``` wrappers
        content = re.sub(r"^```(?:json)?", "", content, flags=re.IGNORECASE).strip()
        content = re.sub(r"```$", "", content).strip()

    try:
        # Try to parse JSON from the response
        result = json.loads(content)
        
        # Validate the response structure
        required_keys = ["completed_actions", "inprogress_actions", "upcoming_actions", "risks_identified"]
        for key in required_keys:
            if key not in result or not isinstance(result[key], list):
                result[key] = []
        
        # Log the structured results
        print("Parsed OpenAI response:")
        print(f"  - Completed actions: {len(result['completed_actions'])} items")
        print(f"  - In-progress actions: {len(result['inprogress_actions'])} items")
        print(f"  - Upcoming actions: {len(result['upcoming_actions'])} items")
        print(f"  - Risks identified: {len(result['risks_identified'])} items")
        
        return result
        
    except json.JSONDecodeError as e:
        print(f"JSON parsing error: {e}")
        print(f"Raw content that failed to parse: {repr(content)}")
        return default_result
    except Exception as e:
        print(f"Unexpected error in response parsing: {e}")
        print(f"Raw content received: {repr(content if 'content' in locals() else 'No content')}")
        return default_result


def summarize_issues_with_openai(issues, openai_api_key):
    """
    Uses OpenAI to extract and summarize completed actions, in-progress actions, upcoming actions, and risks from issues.
    Returns a dict with completed_actions, inprogress_actions, upcoming actions and risks_identified.
    """
    print("Summarizing issues with OpenAI...")
    
    # Prepare issues for analysis
    issue_lines, complexity_score = _prepare_issues_for_analysis(issues)
    issues_text = "\n\n".join(issue_lines)

    # Debug: Print detailed status breakdown
    status_breakdown = {}
    category_breakdown = {
        'completed': 0,
        'inprogress': 0,
        'upcoming': 0,
        'blocked': 0,
        'critical': 0
    }
    
    for line in issue_lines:
        if "✅ COMPLETED" in line:
            category_breakdown['completed'] += 1
        if "🔄 IN-PROGRESS" in line:
            category_breakdown['inprogress'] += 1
        if "📋 UPCOMING" in line:
            category_breakdown['upcoming'] += 1
        if "🚫 BLOCKED" in line:
            category_breakdown['blocked'] += 1
        if "⚠️ CRITICAL PRIORITY" in line:
            category_breakdown['critical'] += 1
    
    print("\n=== INPUT ANALYSIS ===")
    print(f"Expected categorization based on status analysis:")
    print(f"  - Completed issues: {category_breakdown['completed']}")
    print(f"  - In-progress issues: {category_breakdown['inprogress']}")
    print(f"  - Upcoming issues: {category_breakdown['upcoming']}")
    print(f"  - Blocked issues: {category_breakdown['blocked']}")
    print(f"  - Critical priority issues: {category_breakdown['critical']}")
    print(f"  - Total issues prepared: {len(issue_lines)}")
    

    # Create the full prompt with enhanced context
    prompt = _create_openai_prompt()
    full_prompt = f"""{prompt}

STRICT COUNTING REQUIREMENTS:
🔢 EXACT COUNT REQUIREMENTS:
- Total issues to process: {len(issue_lines)}
- Completed issues that MUST appear in completed_actions: {category_breakdown['completed']} (exactly this many items)
- In-progress issues that MUST appear in inprogress_actions: {category_breakdown['inprogress']} (exactly this many items)
- Upcoming issues that MUST appear in upcoming_actions: {category_breakdown['upcoming']} (exactly this many items)
- Blocked/risk issues that MUST appear in risks_identified: {category_breakdown['blocked']} (at minimum this many items)

VERIFICATION CHECKLIST:
✓ completed_actions array length = {category_breakdown['completed']}
✓ inprogress_actions array length = {category_breakdown['inprogress']} 
✓ upcoming_actions array length = {category_breakdown['upcoming']}
✓ risks_identified array length >= {category_breakdown['blocked']}
✓ Total output items = {len(issue_lines)} (sum of all arrays)

INPUT VALIDATION REQUIREMENTS:
- You are receiving {len(issue_lines)} issues to analyze
- Expected breakdown: {category_breakdown['completed']} completed, {category_breakdown['inprogress']} in-progress, {category_breakdown['upcoming']} upcoming, {category_breakdown['blocked']} blocked
- Your output must account for ALL {len(issue_lines)} issues across the four categories
- Use the category hints and guidance provided with each issue

ISSUES TO ANALYZE (sorted by priority - Critical items first):
{issues_text}

MANDATORY REQUIREMENTS:
- Every issue marked with ⚠️ CRITICAL PRIORITY must be explicitly mentioned
- Every issue marked with 🚫 BLOCKED must appear in risks_identified  
- Every issue marked with ⚡ RISK should be considered for risks_identified
- ABSOLUTELY NEVER include issues marked with ✅ COMPLETED in risks_identified section - they belong only in completed_actions
- Completed issues (✅ COMPLETED) are resolved and pose no risk, so exclude them entirely from risks
- Do not let critical items get lost in generic groupings

VALIDATION CHECK: Ensure your response includes all {len(issue_lines)} issues distributed across the four categories.

FINAL VALIDATION REQUIREMENT:
Before submitting your response, count your output items:
- completed_actions: Must have exactly {category_breakdown['completed']} items
- inprogress_actions: Must have exactly {category_breakdown['inprogress']} items  
- upcoming_actions: Must have exactly {category_breakdown['upcoming']} items
- risks_identified: Must have at least {category_breakdown['blocked']} items
- Total: Must equal {len(issue_lines)} items


{_create_example_output()}"""

    # Call OpenAI API
    response = _call_openai_api(full_prompt, openai_api_key, len(issues), complexity_score)
    if not response:
        return {
            "completed_actions": [],
            "inprogress_actions": [],
            "upcoming_actions": [],
            "risks_identified": []
        }

    # Parse and return the response
    result = _parse_openai_response(response)
    
   # Validation: Check if all issues are accounted for
    total_output_items = sum(len(result[key]) for key in result.keys())
    print(f"\n=== OUTPUT VALIDATION ===")
    print(f"Input issues: {len(issue_lines)}")
    print(f"Output items: {total_output_items}")
    print(f"  - Completed actions: {len(result['completed_actions'])}")
    print(f"  - In-progress actions: {len(result['inprogress_actions'])}")
    print(f"  - Upcoming actions: {len(result['upcoming_actions'])}")
    print(f"  - Risks identified: {len(result['risks_identified'])}")
    
    # Detailed validation
    validation_errors = []
    if len(result['completed_actions']) != category_breakdown['completed']:
        validation_errors.append(f"❌ Completed actions mismatch: got {len(result['completed_actions'])}, expected {category_breakdown['completed']}")
    
    if len(result['inprogress_actions']) != category_breakdown['inprogress']:
        validation_errors.append(f"❌ In-progress actions mismatch: got {len(result['inprogress_actions'])}, expected {category_breakdown['inprogress']}")
        
    if len(result['upcoming_actions']) != category_breakdown['upcoming']:
        validation_errors.append(f"❌ Upcoming actions mismatch: got {len(result['upcoming_actions'])}, expected {category_breakdown['upcoming']}")
    
    if total_output_items != len(issue_lines):
        validation_errors.append(f"❌ Total count mismatch: got {total_output_items}, expected {len(issue_lines)}")
    
    if validation_errors:
        print("\n🚨 VALIDATION FAILURES:")
        for error in validation_errors:
            print(f"  {error}")
        print("\nThis indicates OpenAI is grouping issues instead of maintaining 1:1 mapping")
    else:
        print("\n✅ All validation checks passed!")
    
    
    return result

import openai
import json
from datetime import datetime, timedelta
from jira import JIRA
import pytz
import re
import tiktoken

def summarize_issues_with_openai(issues, openai_api_key):
    openai.api_key = openai_api_key
    examples = _create_example_output()
    analyzed_issues = _prepare_issues_for_analysis(issues)
    prompt = _create_openai_prompt(analyzed_issues, examples)
    max_tokens = 2048
    try:
        response = _call_openai_api(prompt, max_tokens)
        return _parse_openai_response(response)
    except Exception as e:
        print(f"OpenAI API error: {e}")
        return "Summary generation failed."

def _prepare_issues_for_analysis(issues):
    analyzed_issues = []
    for issue in issues:
        key = getattr(issue, 'key', '')
        fields = getattr(issue, 'fields', None)
        if not fields:
            continue
        summary = getattr(fields, 'summary', '')
        status = getattr(fields.status, 'name', '')
        comments = []
        if hasattr(fields, 'comment') and hasattr(fields.comment, 'comments'):
            comments = [c.body for c in fields.comment.comments if c.body]
        comments_text = "\n".join(comments)
        analyzed_issues.append(f"Issue {key}: {summary} [{status}]\nComments:\n{comments_text}")
    return analyzed_issues

def _create_openai_prompt(issues_text, examples):
    issues_str = "\n\n".join(issues_text[:15])
    prompt = (
        f"You are a helpful assistant analyzing Jira issues. Based on the issues and comments, provide a summary of key highlights, blockers, questions, risks, and achievements.\n"
        f"Example Format:\n{examples}\n\nAnalyze the following issues:\n{issues_str}\n\nSummary:"
    )
    return prompt

def _call_openai_api(prompt, max_tokens):
    return openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=max_tokens
    )

def _parse_openai_response(response):
    return response.choices[0].message.content.strip()

def _create_example_output():
    return (
        "Highlights:\n- Team completed migration to new service\n"
        "Blockers:\n- API integration delay due to third-party downtime\n"
        "Questions:\n- Need clarity on UX requirements for dashboard\n"
        "Risks:\n- Tight deadline with pending testing\n"
        "Achievements:\n- Delivered MVP two days ahead of schedule"
    )

def estimate_tokens(text, model="gpt-4"):
    enc = tiktoken.encoding_for_model(model)
    return len(enc.encode(text))
