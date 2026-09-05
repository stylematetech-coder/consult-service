"""顧客在表單最後一步選預約日期/時間用的唯讀端點。

只負責「這天能不能點」「這天有哪些時段能選」——真正建立預約(建立
calendar-service 的 event)是 responses.py 的 POST /responses/{id}/booking，
那支才會呼叫 calendar-service 的認證 API 做最終把關(營業時間/cutoff/衝突
都由 calendar-service 自己的 events.ts 再驗一次，這裡的判斷只是給 UI 用，
不是安全邊界)。
"""
import calendar as _calendar_module
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException

from .. import calendar_client as cal

router = APIRouter()

_SLOT_STEP_MINUTES = 30


def _weekday_index(d: date) -> int:
    # Python's date.weekday(): Mon=0..Sun=6 — already the same convention
    # calendar-service's BusinessDay.weekday uses (see businessHours.ts).
    return d.weekday()


def _day_rule(hours_doc: dict | None, d: date) -> tuple[bool, str | None, str | None]:
    """(closed, open_time, close_time) for one date — date_overrides win
    outright over the weekly pattern, same precedence as
    `findBusinessHoursViolation` in businessHours.ts. No document at all =
    fail-open (fully open), same convention as that function."""
    if hours_doc is None:
        return False, "00:00", "24:00"

    date_str = d.isoformat()
    for override in hours_doc.get("date_overrides", []):
        if override["date"] == date_str:
            return override["closed"], override.get("open_time"), override.get("close_time")

    weekday = _weekday_index(d)
    for day in hours_doc.get("days", []):
        if day["weekday"] == weekday:
            return day["closed"], day.get("open_time"), day.get("close_time")
    return True, None, None


@router.get("/availability/business-hours")
def get_business_hours(year_month: str):
    """`year_month`："YYYY-MM"。回傳該月每一天是否可點，給表單月曆畫面把
    沒營業的日期直接 disable。"""
    try:
        year, month = (int(p) for p in year_month.split("-"))
    except ValueError:
        raise HTTPException(status_code=400, detail="year_month must be YYYY-MM")

    user_id = cal.get_owner_user_id()
    hours_doc = cal.get_business_hours(user_id) if user_id else None

    days_in_month = _calendar_module.monthrange(year, month)[1]
    result = []
    for day_num in range(1, days_in_month + 1):
        d = date(year, month, day_num)
        closed, open_time, close_time = _day_rule(hours_doc, d)
        result.append(
            {
                "date": d.isoformat(),
                "closed": closed,
                "open_time": open_time,
                "close_time": close_time,
            }
        )
    return {"days": result}


def _category_cutoff_time(hours_doc: dict | None, service: str) -> str | None:
    """Strictest (earliest) cutoff among `service`'s categories, or None if
    none apply — mirrors `findCategoryCutoffViolation`'s "combo is bound by
    whichever category has the earliest cutoff" rule."""
    if hours_doc is None:
        return None
    cutoffs = hours_doc.get("category_cutoffs") or {}
    strictest: str | None = None
    for category in cal.parse_service_categories(service):
        cutoff = cutoffs.get(category)
        if not cutoff or not cutoff.get("restricted") or not cutoff.get("cutoff_time"):
            continue
        if strictest is None or cutoff["cutoff_time"] < strictest:
            strictest = cutoff["cutoff_time"]
    return strictest


@router.get("/availability/slots")
def get_slots(date_str: str, service: str, gender: str):
    """`date_str`："YYYY-MM-DD"。`service`：跟 answers['services'] 換算後的
    中文服務字串一致(例如 "染髮、燙髮")。回傳這天可以點的起始時間清單
    ("HH:MM")——只要出現在清單裡就代表可點，前端不用再自己重算一次。
    """
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

    user_id = cal.get_owner_user_id()
    if not user_id:
        return {"slots": []}

    hours_doc = cal.get_business_hours(user_id)
    closed, open_time, close_time = _day_rule(hours_doc, d)
    if closed or not open_time or not close_time:
        return {"slots": []}

    duration = cal.estimate_duration_minutes(user_id, service, gender) or _SLOT_STEP_MINUTES
    cutoff = _category_cutoff_time(hours_doc, service)
    latest_start = min(close_time, cutoff) if cutoff else close_time

    day_start_utc = cal.local_to_utc_iso(datetime.combine(d, datetime.min.time()))
    day_end_utc = cal.local_to_utc_iso(datetime.combine(d + timedelta(days=1), datetime.min.time()))
    existing_events = cal.get_events_in_range(user_id, day_start_utc, day_end_utc)

    now_local = datetime.now(cal.LOCAL_TZ).replace(tzinfo=None)

    open_h, open_m = (int(p) for p in open_time.split(":"))
    day_start = datetime.combine(d, datetime.min.time())
    first_candidate = day_start.replace(hour=open_h, minute=open_m)

    # Bounded by one calendar day's worth of steps (not a `while True` on
    # the HH:MM string) — `latest_start` can be "24:00" in the fail-open
    # "no business_hours document yet" case, and "00:00" (next day, from
    # `cursor` rolling over midnight) never compares greater than that, so
    # an unbounded loop here would spin forever.
    slots: list[str] = []
    for step in range(0, 24 * 60 // _SLOT_STEP_MINUTES):
        cursor = first_candidate + timedelta(minutes=step * _SLOT_STEP_MINUTES)
        if cursor.date() != d:
            break
        candidate_hhmm = cursor.strftime("%H:%M")
        if candidate_hhmm > latest_start:
            break
        if cursor < now_local:
            continue
        candidate_end = cursor + timedelta(minutes=duration)
        start_utc = cal.local_to_utc_iso(cursor)
        end_utc = cal.local_to_utc_iso(candidate_end)
        conflict = any(
            start_utc < e["end_time"] and end_utc > e["start_time"] for e in existing_events
        )
        if not conflict:
            slots.append(candidate_hhmm)

    return {"slots": slots}
