import re
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from ..db import is_same_local_day, responses_col, schemas_col, utc_now_iso
from ..notify import notify_form_submitted

router = APIRouter()

# 台灣手機號碼固定 09 開頭共 10 碼。前端已經有防呆（即時濾除非數字、格式檢查），
# 這裡是後端這層再擋一次，避免有人繞過前端直接打 API。
PHONE_PATTERN = re.compile(r"^09\d{8}$")

# LINE userId 格式（U + 32 個十六進位字元）。這個值從表單網址的 ?uid= 帶進來，
# 用途是讓 LINE bot 那側把「填完表單」對回正確的聊天室；它是「識別」不是「認證」
# （query string 可被改），所以格式不對就當作沒有，不因此擋掉整張表單。
LINE_UID_PATTERN = re.compile(r"^U[0-9a-f]{32}$")


class CreateResponseBody(BaseModel):
    name: str = Field(min_length=1)
    phone: str = Field(min_length=1)
    gender: str = Field(min_length=1)
    line_uid: str | None = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        v = v.strip()
        if not PHONE_PATTERN.match(v):
            raise ValueError("手機號碼格式不正確，需為 09 開頭的 10 碼數字")
        return v

    @field_validator("line_uid")
    @classmethod
    def validate_line_uid(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v if LINE_UID_PATTERN.match(v) else None


class PatchAnswersBody(BaseModel):
    answers: dict


def _parse_object_id(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except InvalidId:
        raise HTTPException(status_code=404, detail="Response not found")


def _doc_to_response(doc: dict, include_answers: bool = True) -> dict:
    data = {
        "id": str(doc["_id"]),
        "schema_id": doc["schema_id"],
        "name": doc["name"],
        "phone": doc["phone"],
        "gender": doc["gender"],
        "line_uid": doc.get("line_uid"),
        "status": doc["status"],
        "created_at": doc["created_at"],
        "submitted_at": doc.get("submitted_at"),
        # 2026-08-04:這張表單描述的需求是否已經被排進行事曆。預設
        # unscheduled，agent 呼叫 calendar_create 成功後才會標成 scheduled；
        # 之後那筆預約被取消(calendar_delete)又會標回 unscheduled——見
        # PATCH /responses/{id}/booking。
        "booking_status": doc.get("booking_status", "unscheduled"),
        "booked_datetime": doc.get("booked_datetime"),
        "booked_event_id": doc.get("booked_event_id"),
    }
    if include_answers:
        data["answers"] = doc.get("answers", {})
    return data


@router.post("/responses", status_code=201)
def create_response(body: CreateResponseBody):
    """Start a new form. One customer (one line_uid) can hold MANY of these
    over time (2026-08-03 product decision, reversing the same-day's earlier
    "one per phone" experiment) — different visits are different needs
    (剪髮 today, 染髮 next month), so each new form is its own document,
    never an overwrite of a prior one. `line_uid` is what scopes "which forms
    are this customer's" for the dashboard (GET /responses/mine) — phone is
    NOT unique and is not an identity boundary (see db.py).
    """
    active = schemas_col.find_one({"is_active": True}, sort=[("_id", -1)])
    if active is None:
        raise HTTPException(status_code=500, detail="No active questionnaire schema configured")

    name = body.name.strip()
    gender = body.gender.strip()
    now = datetime.now(timezone.utc)

    # 同一位客人(同一個 line_uid)當天如果還有沒填完的草稿,接著用同一筆,不要
    # 疊出一堆填一半的重複紀錄;隔天再來就當作是新的一次諮詢。沒有 line_uid
    # (理論上不該發生,新流程一律透過帶 uid 的連結進來)就不做這個接續判斷,
    # 每次都當新的一筆。
    draft = None
    if body.line_uid:
        draft = responses_col.find_one(
            {"line_uid": body.line_uid, "status": "in_progress"}, sort=[("_id", -1)]
        )
    if draft and is_same_local_day(draft["created_at"], now):
        update = {"name": name, "gender": gender, "answers.gender": gender}
        responses_col.update_one({"_id": draft["_id"]}, {"$set": update})
        doc = responses_col.find_one({"_id": draft["_id"]})
        result = _doc_to_response(doc)
        result["resumed"] = True
        result["prefilled"] = False
        return {"response": result}

    # 新的一次填寫。把這位客人(同一個 line_uid)最近一次「已送出」的答案帶過來
    # 當初始值,讓顧客直接在上面修改,不用每次都從空白重新填一遍——這只是預填
    # 方便,不是同一筆紀錄,送出後是獨立的新文件。
    prior = None
    if body.line_uid:
        prior = responses_col.find_one(
            {"line_uid": body.line_uid, "status": "submitted"}, sort=[("submitted_at", -1)]
        )
    initial_answers = {**prior["answers"], "gender": gender} if prior else {"gender": gender}

    doc = {
        "schema_id": str(active["_id"]),
        "name": name,
        "phone": body.phone,
        "gender": gender,
        "line_uid": body.line_uid,
        "status": "in_progress",
        "answers": initial_answers,
        "created_at": utc_now_iso(),
        "submitted_at": None,
        "booking_status": "unscheduled",
        "booked_datetime": None,
        "booked_event_id": None,
    }
    insert_result = responses_col.insert_one(doc)
    doc["_id"] = insert_result.inserted_id
    result = _doc_to_response(doc)
    result["resumed"] = False
    result["prefilled"] = prior is not None
    return {"response": result}


@router.patch("/responses/{response_id}")
def update_answers(response_id: str, body: PatchAnswersBody):
    oid = _parse_object_id(response_id)
    doc = responses_col.find_one({"_id": oid})
    if doc is None:
        raise HTTPException(status_code=404, detail="Response not found")
    if doc["status"] != "in_progress":
        raise HTTPException(status_code=409, detail="Response already submitted")

    responses_col.update_one({"_id": oid}, {"$set": {"answers": body.answers}})
    doc = responses_col.find_one({"_id": oid})
    return {"response": _doc_to_response(doc)}


@router.post("/responses/{response_id}/submit")
def submit_response(response_id: str):
    oid = _parse_object_id(response_id)
    doc = responses_col.find_one({"_id": oid})
    if doc is None:
        raise HTTPException(status_code=404, detail="Response not found")

    responses_col.update_one(
        {"_id": oid},
        {"$set": {"status": "submitted", "submitted_at": utc_now_iso()}},
    )
    doc = responses_col.find_one({"_id": oid})

    # If this form came from a LINE chat (has line_uid), tell the bot so it can
    # continue the booking in LINE. Best-effort: never let it break submit.
    try:
        schema = schemas_col.find_one({"_id": _parse_object_id(doc["schema_id"])})
        notify_form_submitted(doc, (schema or {}).get("steps", []))
    except Exception:  # noqa: BLE001
        pass

    return {"response": _doc_to_response(doc)}


# NOTE: 這兩個查詢端點目前沒有任何驗證機制，會回傳顧客姓名＋手機號碼。
# 這個服務如果之後跟著 integrate/ 一起用 ngrok 對外開放，任何人都能查到
# 所有顧客的名單。之後要補驗證時，比照 calendar-service 的 JWT 中介層即可。
@router.get("/responses")
def list_responses(phone: str):
    docs = responses_col.find({"phone": phone.strip()}).sort("created_at", -1)
    return {"responses": [_doc_to_response(doc, include_answers=False) for doc in docs]}


# 一定要放在 `/responses/{response_id}` 之前註冊：Starlette 依註冊順序比對路由，
# 放後面的話 "/responses/mine" 會先被 {response_id} 那個路由吃掉("mine" 被當成
# id，ObjectId 解析失敗變成 404)。
@router.get("/responses/mine")
def list_my_responses(line_uid: str):
    """這位客人(同一個 line_uid)自己的表單列表，給客人自己的「我的表單」
    儀表板用——依 line_uid 篩選，不是 phone，客人只看得到自己曾經開過的表單。
    """
    docs = responses_col.find({"line_uid": line_uid.strip()}).sort("created_at", -1)
    return {"responses": [_doc_to_response(doc, include_answers=False) for doc in docs]}


@router.get("/responses/{response_id}")
def get_response(response_id: str):
    oid = _parse_object_id(response_id)
    doc = responses_col.find_one({"_id": oid})
    if doc is None:
        raise HTTPException(status_code=404, detail="Response not found")
    return {"response": _doc_to_response(doc)}
