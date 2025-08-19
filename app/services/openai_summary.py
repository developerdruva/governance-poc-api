from openai import OpenAI
import openai
import json

def summarize_issues_with_openai(issues, api_key):
    openai.api_key = api_key
    # This is a placeholder - you can paste your full OpenAI analysis logic from common_util_ai.py
    prompt = """Summarize these JIRA issues into completed, in-progress, upcoming, risks..."""
    issue_summaries = [f"{i.key}: {i.fields.summary}" for i in issues if hasattr(i, 'fields')]
    full_prompt = prompt + "\n" + "\n".join(issue_summaries)

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a project manager AI assistant."},
                {"role": "user", "content": full_prompt}
            ],
            temperature=0.2,
            max_tokens=2048,
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {"error": str(e)}