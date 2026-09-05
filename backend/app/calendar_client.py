"""Read/write access to calendar-service's data, for the "選預約時間" step
added to the end of the consultation form (2026-09-05).

Two different integration styles on purpose, mirroring the pattern already
used by skills/calendar-booking/mcp-server/server.py for the exact same pair
of services:

- READS (business hours, existing events, service-duration settings) go
  straight at calendar-service's own MongoDB — same "same cluster, separate
  database" shared-Mongo setup this repo already uses in the other
  direction (calendar-service's src/db/index.ts reads consult-service's
  `responses`/`questionnaire_schemas` directly). These are read-only, with
  no validation logic worth duplicating.
- The WRITE that actually creates a booking goes through calendar-service's
  authenticated HTTP API (`POST /events`), NOT a direct Mongo insert. That
  endpoint is where `findBusinessHoursViolation`/`findCategoryCutoffViolation`/
  the time-conflict check actually live (calendar-service's
  src/routes/events.ts) — porting all three into Python here would just be a
  second copy that can silently drift from the original. The MCP server made
  the same call for the same reason (see its own `_calendar_request`).

calendar-service has exactly ONE login in practice (see the MCP server's own
comment on this) — every booking, from every channel, is written under that
one store account. `CALENDAR_OWNER_EMAIL` below is that account, looked up
once and cached; it is not a real multi-tenant selector.
"""
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from pymongo import MongoClient

from .db import LOCAL_TZ, MONGO_URI

logger = logging.getLogger(__name__)

CALENDAR_MONGO_DB = os.environ.get("CALENDAR_MONGO_DB", "calendar_service")
CALENDAR_BASE_URL = os.environ.get("CALENDAR_BASE_URL", "http://localhost:3001").rstrip("/")
CALENDAR_OWNER_EMAIL = os.environ.get("CALENDAR_OWNER_EMAIL", "admin@example.com")
CALENDAR_OWNER_PASSWORD = os.environ.get("CALENDAR_OWNER_PASSWORD", "12345678")

_TIMEOUT_SECONDS = 10

# Same Mongo server as consult-service's own `_client` (db.py) — a second
# database handle on a NEW client, matching calendar-service's own
# `client.db(CONSULT_MONGO_DB_NAME)` pattern in reverse (src/db/index.ts).
_cal_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
_cal_db = _cal_client[CALENDAR_MONGO_DB]
users_col = _cal_db["users"]
business_hours_col = _cal_db["business_hours"]
events_col = _cal_db["events"]
service_durations_col = _cal_db["service_durations"]

# Must match calendar-service's own SERVICE_CATEGORIES (src/db/index.ts) and
# the six category labels used as `label` on the schema's `services` step
# options (question_schema_v1.py) — three independent codebases sharing one
# label set, no shared import between them (documented invariant, not
# enforced in code, same as this project's STORE_TZ situation).
SERVICE_CATEGORIES = ["剪髮", "燙髮", "染髮", "接髮", "頭皮護理", "護髮"]
_SERVICE_SPLIT_RE = re.compile(r"[、,，/\s]+")

_owner_user_id: str | None = None
_owner_user_id_lock = threading.Lock()


def get_owner_user_id() -> str | None:
    """calendar-service's single owner account's `_id`, as a string.

    Cached after the first lookup — this doesn't change at runtime. Returns
    None if the account hasn't been registered yet (fresh calendar-service
    with no owner set up), same fail-open posture as the rest of this
    module: nothing to gate against yet.
    """
    global _owner_user_id
    if _owner_user_id is not None:
        return _owner_user_id
    with _owner_user_id_lock:
        if _owner_user_id is not None:
            return _owner_user_id
        doc = users_col.find_one({"email": CALENDAR_OWNER_EMAIL})
        if doc is None:
            return None
        _owner_user_id = str(doc["_id"])
        return _owner_user_id


def parse_service_categories(service: str) -> list[str]:
    """Mirrors businessHours.ts's `parseServiceCategories` exactly (same
    delimiter set, same fixed six categories, unknown tokens dropped)."""
    return [t for t in _SERVICE_SPLIT_RE.split(service) if t in SERVICE_CATEGORIES]


def get_business_hours(user_id: str) -> dict | None:
    """Raw `business_hours` document, or None if the owner never configured
    hours — callers should fail OPEN on None (see businessHours.ts's own
    "unconfigured = off" convention), not treat it as "always closed"."""
    return business_hours_col.find_one({"user_id": user_id})


def get_events_in_range(user_id: str, start_utc_iso: str, end_utc_iso: str) -> list[dict]:
    """Events overlapping [start, end) UTC — same overlap test as
    events.ts's `findConflict`."""
    return list(
        events_col.find(
            {
                "user_id": user_id,
                "start_time": {"$lt": end_utc_iso},
                "end_time": {"$gt": start_utc_iso},
            }
        )
    )


def _term_key(terms: list[str]) -> tuple[str, ...]:
    return tuple(sorted(terms))


def estimate_duration_minutes(user_id: str, service: str, gender: str) -> int:
    """Port of calendar-service's `POST /service-durations/estimate` (see
    routes/service-durations.ts) — kept here as a straight read + simple
    arithmetic, not a validation gate, so duplicating it doesn't carry the
    same drift risk `findBusinessHoursViolation` et al. would.
    """
    categories = parse_service_categories(service)
    if not categories:
        return 0

    doc = service_durations_col.find_one({"user_id": user_id})
    default_categories = {"剪髮": 30, "燙髮": 90, "染髮": 60, "接髮": 120, "頭皮護理": 45, "護髮": 45}
    base = (doc or {}).get("categories") or default_categories

    if len(categories) == 1:
        return int(base.get(categories[0], 0))

    formulas_key = "formulas_male" if gender == "male" else "formulas_female"
    formulas = (doc or {}).get(formulas_key) or []
    key = _term_key(categories)
    for formula in formulas:
        if _term_key(formula.get("terms", [])) == key:
            return int(formula["duration_minutes"])

    total = sum(int(base.get(c, 0)) for c in categories)
    return round(total * 0.8)


_UID_TAG_PREFIX = "line_uid:"
_PHONE_TAG_PREFIX = "phone:"


def make_description(line_uid: str | None, phone: str = "", note: str = "") -> str:
    """MUST match the MCP server's `_make_description` exactly (same
    delimiter, same prefixes) — that function, and this one, are now BOTH
    writers of this identity tag; calendar-service's own
    `extractLineUid`/`_event_line_uid` readers don't care which wrote it, as
    long as the format matches.
    """
    parts = []
    if line_uid:
        parts.append(f"{_UID_TAG_PREFIX}{line_uid.strip()}")
    if phone:
        parts.append(f"{_PHONE_TAG_PREFIX}{phone.strip()}")
    if note:
        parts.append(note)
    return "／".join(parts)


def local_to_utc_iso(local_dt: datetime) -> str:
    """Naive datetime (Asia/Taipei wall-clock) -> UTC ISO 8601 in the exact
    "...000Z" shape calendar-service's own `z.string().datetime()` schema
    (routes/events.ts) and the MCP server's `_local_to_utc_iso` both use."""
    aware = local_dt.replace(tzinfo=LOCAL_TZ)
    return aware.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


_token: str | None = None
_token_lock = threading.Lock()


def _login() -> str:
    body = json.dumps(
        {"email": CALENDAR_OWNER_EMAIL, "password": CALENDAR_OWNER_PASSWORD}
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{CALENDAR_BASE_URL}/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read())["token"]


def _get_token(force_refresh: bool = False) -> str:
    global _token
    if _token and not force_refresh:
        return _token
    with _token_lock:
        if _token and not force_refresh:
            return _token
        _token = _login()
        return _token


def _events_request(
    method: str, path: str, json_body: dict | None = None, retry_on_401: bool = True
) -> dict:
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"{CALENDAR_BASE_URL}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            return {"status": resp.status, "body": json.loads(resp.read() or b"{}")}
    except urllib.error.HTTPError as exc:
        payload = json.loads(exc.read() or b"{}")
        if exc.code == 401 and retry_on_401:
            _get_token(force_refresh=True)
            return _events_request(method, path, json_body, retry_on_401=False)
        return {"status": exc.code, "body": payload}


def delete_event(event_id: str) -> dict:
    """DELETE /events/{id} — best-effort cleanup when a customer re-picks a
    slot after already booking once (see routers/responses.py's booking
    endpoint): the OLD event must be removed before a new one is created,
    or it's left dangling on the owner's calendar forever. A 404 here is
    fine (event already gone) — callers should not treat it as fatal."""
    return _events_request("DELETE", f"/events/{event_id}")


def create_event(
    customer_name: str,
    service: str,
    start_local: datetime,
    end_local: datetime,
    line_uid: str | None,
    phone: str = "",
    note: str = "",
) -> dict:
    """POST /events on calendar-service under the store's single owner
    account. Returns the raw `{"status": int, "body": dict}` response —
    callers decide how to translate 201/409/422 into a customer-facing
    message (see routers/responses.py's booking endpoint)."""
    return _events_request(
        "POST",
        "/events",
        {
            "customer_name": customer_name,
            "service": service,
            "description": make_description(line_uid, phone, note),
            "start_time": local_to_utc_iso(start_local),
            "end_time": local_to_utc_iso(end_local),
        },
    )
