from app.slack import post_to_slack


def format_message(event_type: str, payload: dict) -> str:
    repo = payload.get("repository", {}).get("full_name", "")
    action = payload.get("action", "")
    return f"*[{repo}]* GitHub `{event_type}` event — action: `{action}`"


def process_github_event(event_type: str, payload: dict) -> None:
    # RQ workers are synchronous — post_to_slack is sync, which is correct here.
    message = format_message(event_type, payload)  # replaced by Claude in Slice 5
    post_to_slack(message)
