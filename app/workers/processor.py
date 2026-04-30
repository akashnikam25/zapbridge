from app.slack import post_to_slack


def format_message(event_type: str, payload: dict) -> str:
    repo = payload.get("repository", {}).get("full_name", "")
    action = payload.get("action", "")
    url = (
        payload.get("pull_request", {}).get("html_url")
        or payload.get("issue", {}).get("html_url")
        or payload.get("repository", {}).get("html_url", "")
    )
    repo_link = f"<{url}|{repo}>" if url else repo
    return f"*[{repo_link}]* GitHub `{event_type}` event — action: `{action}`"


def process_github_event(event_type: str, payload: dict) -> None:
    # RQ workers are synchronous — post_to_slack is sync, which is correct here.
    message = format_message(event_type, payload)  # replaced by Claude in Slice 5
    post_to_slack(message)
