"""Notify the LINE bot when a customer submits the web form.

The form is opened from a LINE chat via a link carrying `?uid=<LINE userId>`
(stored as `line_uid`). On submit we POST a readable summary to the bot's
`/hooks/form-submitted`, so it can feed the content to that customer's agent
session and continue the booking conversation in LINE.

Deliberately best-effort and non-blocking: the POST runs in a daemon thread
with a short timeout and every failure is swallowed. Submitting the form must
succeed even if the bot is down, misconfigured, or slow — the notification is
a convenience, not part of the form's own contract.

Uses stdlib urllib (no extra dependency). Config via env:
    LINEBOT_HOOK_URL    e.g. http://localhost:8000/hooks/form-submitted
    LINEBOT_HOOK_TOKEN  shared secret; must equal the bot's FORM_HOOK_TOKEN
    LINEBOT_TENANT      which store the customer belongs to (default "default")
Missing URL or token → notification is silently skipped.
"""
import json
import logging
import os
import threading
import urllib.request

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 5

# Steps of type "info" are designer-reference (derived suggestions), not
# customer answers — leave them out of the summary sent to the bot.
_SKIP_TYPES = {"info"}


def _option_labels(step: dict) -> dict[str, str]:
    """value → label for a step, covering static and source-dependent options."""
    labels: dict[str, str] = {}
    for opt in step.get("options") or []:
        labels[opt["value"]] = opt["label"]
    src = step.get("optionsBySource")
    if src:
        for group in list(src.get("map", {}).values()) + [src.get("default", [])]:
            for opt in group:
                labels.setdefault(opt["value"], opt["label"])
    return labels


def _format_answer(step: dict, answers: dict) -> str | None:
    """Human-readable answer for one step, or None if unanswered."""
    value = answers.get(step["id"])
    if value in (None, "", []):
        return None
    labels = _option_labels(step)
    other_value = step.get("otherValue")
    other_text = answers.get(f"{step['id']}Other")

    def one(v: str) -> str:
        if other_value and v == other_value and isinstance(other_text, str) and other_text.strip():
            return f"其他：{other_text.strip()}"
        return labels.get(v, str(v))

    if isinstance(value, list):
        parts = [one(v) for v in value]
        return "、".join(p for p in parts if p) or None
    return one(value) if labels else str(value)


def summarize(steps: list[dict], answers: dict) -> tuple[str | None, str]:
    """Return (service, multi-line summary) from the schema steps + answers.

    `service` is the answer to the `services` step (the booking's 預約項目);
    the summary is every answered step as "標籤：值" lines.
    """
    service: str | None = None
    lines: list[str] = []
    for step in steps:
        if step.get("type") in _SKIP_TYPES:
            continue
        formatted = _format_answer(step, answers)
        if formatted is None:
            continue
        if step["id"] == "services":
            service = formatted
        label = step.get("summaryLabel") or step.get("question") or step["id"]
        lines.append(f"{label}：{formatted}")
    return service, "\n".join(lines)


def _post(payload: dict) -> None:
    url = os.environ.get("LINEBOT_HOOK_URL", "").strip()
    token = os.environ.get("LINEBOT_HOOK_TOKEN", "").strip()
    if not url or not token:
        logger.info("LINE hook not configured — skipping form-submitted notify")
        return
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            logger.info("form-submitted notify → LINE bot: HTTP %s", resp.status)
    except Exception as exc:  # noqa: BLE001 - best effort, never break submit
        logger.warning("form-submitted notify failed (ignored): %s", exc)


def notify_form_submitted(doc: dict, steps: list[dict]) -> None:
    """Fire-and-forget: tell the LINE bot this form was submitted.

    No-op unless the response carries a line_uid (i.e. it came from a LINE
    chat). Runs the HTTP call on a daemon thread so submit() returns at once.
    """
    line_uid = doc.get("line_uid")
    if not line_uid:
        return
    service, summary = summarize(steps, doc.get("answers", {}))
    payload = {
        "line_uid": line_uid,
        "tenant": os.environ.get("LINEBOT_TENANT", "default"),
        "name": doc.get("name"),
        "phone": doc.get("phone"),
        "gender": doc.get("gender"),
        "service": service,
        "summary": summary,
    }
    threading.Thread(target=_post, args=(payload,), daemon=True).start()
