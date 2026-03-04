import os
import json
import requests
from github import Github, Auth

gh_token = os.environ.get("GITHUB_TOKEN")
gemini_key = os.environ.get("GEMINI_API_KEY")
repo_name = os.environ.get("REPOSITORY")
event_name = os.environ.get("EVENT_NAME")
allowed_user = os.environ.get("ALLOWED_USER").strip().lower()

auth = Auth.Token(gh_token)
gh = Github(auth=auth)
repo = gh.get_repo(repo_name)

diff_text = ""
event_context = ""
author_login = ""

if event_name == "push":
    commit_sha = os.environ.get("COMMIT_SHA")
    commit = repo.get_commit(commit_sha)
    if not commit.author:
        exit(0)
    author_login = commit.author.login.strip().lower()
    if author_login != allowed_user:
        exit(0)
    event_context = f"Commit Message: {commit.commit.message}"
    for file in commit.files:
        diff_text += f"File: {file.filename}\nPatch:\n{file.patch}\n\n"
        if len(diff_text) > 100000:
            diff_text += "\n[Diff too large, truncated...]"
            break
elif event_name == "pull_request":
    pr_number = int(os.environ.get("PR_NUMBER"))
    pr = repo.get_pull(pr_number)
    author_login = pr.user.login.strip().lower()
    if author_login != allowed_user:
        exit(0)
    event_context = f"PR Title: {pr.title}\nPR Body: {pr.body}"
    for file in pr.get_files():
        diff_text += f"File: {file.filename}\nPatch:\n{file.patch}\n\n"
        if len(diff_text) > 100000:
            diff_text += "\n[Diff too large, truncated...]"
            break
else:
    exit(0)

prompt = f"""
Analyze the following code changes and create a detailed description for a GitHub Issue.
IMPORTANT: The issue_title and issue_body MUST be written entirely in English.

Context:
{event_context}

Code Changes:
{diff_text}

Instructions:
1. Create a clear issue title and body explaining the changes or implementation details in English.
2. Choose the most appropriate labels from: ["bug", "documentation", "duplicate", "enhancement", "good first issue", "help wanted", "invalid", "question", "wontfix"].
3. SECURITY REVIEW: Carefully analyze the code changes for any potential security vulnerabilities (e.g., injection flaws, hardcoded secrets, XSS, insecure data handling).
   - If you find a potential vulnerability, add a section "### Security Warning" at the end of the `issue_body` describing the risk and how to fix it in English.
   - Also, if a vulnerability is found, add the label "security" to the `labels` list.

Return only a raw JSON object with no markdown formatting. The JSON must contain these exact keys:
"issue_title": string,
"issue_body": string,
"labels": list of strings
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
