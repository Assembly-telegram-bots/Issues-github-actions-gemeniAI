import os
import json
import re
import requests
from github import Github, Auth

gh_token = os.environ.get("GITHUB_TOKEN")
gemini_key = os.environ.get("GEMINI_API_KEY")
repo_name = os.environ.get("REPOSITORY")
event_name = os.environ.get("EVENT_NAME")
allowed_users = [u.strip().lower() for u in os.environ.get("ALLOWED_USER", "").split(",")]

auth = Auth.Token(gh_token)
gh = Github(auth=auth)
repo = gh.get_repo(repo_name)

diff_text = ""
event_context = ""
author_login = ""
trigger_labels = []

if event_name == "push":
    commit_sha = os.environ.get("COMMIT_SHA")
    commit = repo.get_commit(commit_sha)
    if not commit.author:
        exit(0)
    author_login = commit.author.login.strip().lower()
    if author_login not in allowed_users:
        exit(0)
    event_context = f"Commit Message: {commit.commit.message}"
    trigger_labels = [m.lower() for m in re.findall(r'\[(.*?)\]', commit.commit.message)]
    for file in commit.files:
        diff_text += f"File: {file.filename}\nPatch:\n{file.patch}\n\n"
        if len(diff_text) > 100000:
            diff_text += "\n[Diff too large, truncated...]"
            break
elif event_name == "pull_request":
    pr_number = int(os.environ.get("PR_NUMBER"))
    pr = repo.get_pull(pr_number)
    author_login = pr.user.login.strip().lower()
    if author_login not in allowed_users:
        exit(0)
    event_context = f"PR Title: {pr.title}\nPR Body: {pr.body}"
    trigger_labels = [label.name.lower() for label in pr.labels]
    for file in pr.get_files():
        diff_text += f"File: {file.filename}\nPatch:\n{file.patch}\n\n"
        if len(diff_text) > 100000:
            diff_text += "\n[Diff too large, truncated...]"
            break
else:
    exit(0)

base_instructions = """
Return only a raw JSON object with no markdown formatting. The JSON must contain these exact keys:
"issue_title": string,
"issue_body": string,
"labels": list of strings
The issue_title and issue_body MUST be written entirely in English. Choose appropriate standard GitHub labels for the 'labels' list.
"""

if any(l in trigger_labels for l in ["sec", "security", "audit"]):
    prompt = f"""
    Act as a Strict Security Auditor. Perform a deep security audit on the following code changes based on OWASP Top 10.
    Context: {event_context}
    Changes: {diff_text}
    Instructions: Look for injection flaws, XSS, hardcoded secrets, and insecure data handling. Create a critical vulnerability report in the issue_body detailing the exact lines and how to patch them.
    {base_instructions}
    """
elif any(l in trigger_labels for l in ["review", "refactor", "code-review"]):
    prompt = f"""
    Act as a Strict Code Reviewer. Analyze the following code changes focusing on code quality, SOLID principles, DRY, and architecture.
    Context: {event_context}
    Changes: {diff_text}
    Instructions: Identify code smells, bad naming conventions, or redundant logic. Create an issue with concrete refactoring improvements and code snippets showing the better approach.
    {base_instructions}
    """
elif any(l in trigger_labels for l in ["qa", "test", "testing"]):
    prompt = f"""
    Act as a QA Engineer. Analyze the following code changes to identify edge cases and potential points of failure.
    Context: {event_context}
    Changes: {diff_text}
    Instructions: Generate ready-to-use unit test code blocks and a bulleted checklist for manual testing inside the issue_body.
    {base_instructions}
    """
elif any(l in trigger_labels for l in ["perf", "performance", "optimize"]):
    prompt = f"""
    Act as a Performance Expert. Analyze the following code changes for performance bottlenecks, time/space complexity, and resource leaks.
    Context: {event_context}
    Changes: {diff_text}
    Instructions: Identify slow loops, redundant database calls, or high memory usage. Provide algorithmic optimizations in the issue_body.
    {base_instructions}
    """
elif any(l in trigger_labels for l in ["pm", "release", "product"]):
    prompt = f"""
    Act as a Product Manager. Analyze the following code changes and generate user-facing Release Notes.
    Context: {event_context}
    Changes: {diff_text}
    Instructions: Translate technical code changes into business value and clear user benefits. Format the issue_body as a public changelog.
    {base_instructions}
    """
else:
    prompt = f"""
    Analyze the following code changes and create a standard documentation issue.
    Context: {event_context}
    Changes: {diff_text}
    Instructions: Create a clear description of what was changed. Add a "### Security Warning" section at the end ONLY if you spot an obvious security flaw.
    {base_instructions}
    """

model_name = "gemini-2.5-flash"
api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
payload = {"contents": [{"parts": [{"text": prompt}]}]}
headers = {"Content-Type": "application/json"}

resp = requests.post(api_url, json=payload, headers=headers)
resp_data = resp.json()

response_text = resp_data['candidates'][0]['content']['parts'][0]['text'].strip()

if response_text.startswith("```json"):
    response_text = response_text[7:]
elif response_text.startswith("```"):
    response_text = response_text[3:]
    
if response_text.endswith("```"):
    response_text = response_text[:-3]
    
response_text = response_text.strip()
result = json.loads(response_text)

if event_name == "push":
    footer = f"\n\n---\n*Generated automatically from commit {os.environ.get('COMMIT_SHA')[:7]}*"
else:
    footer = f"\n\n---\n*Generated automatically from PR #{os.environ.get('PR_NUMBER')}*"

repo.create_issue(
    title=result['issue_title'],
    body=result['issue_body'] + footer,
    labels=result.get('labels', [])
)
