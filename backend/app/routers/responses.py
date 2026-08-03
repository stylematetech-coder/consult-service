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
    }
    if include_answers:
        data["answers"] = doc.get("answers", {})
    return data


@router.post("/responses", status_code=201)
def create_response(body: CreateResponseBody):
    active = schemas_col.find_one({"is_active": True}, sort=[("_id", -1)])
    if active is None:
        raise HTTPException(status_code=500, detail="No active questionnaire schema configured")

    name = body.name.strip()
    gender = body.gender.strip()
    now = datetime.now(timezone.utc)

    # 每支電話只保留一筆(2026-08-03 起，不再累積歷史紀錄)：existing 是這支
    # 電話目前唯一的一筆(不論狀態是 in_progress 還是 submitted)，下面每個
    # 分支都圍繞著它更新，不會再對同一支電話 insert 出第二筆文件。
    existing = responses_col.find_one({"phone": body.phone}, sort=[("_id", -1)])

    # 防呆：同一支電話不能對應到不同姓名，避免打錯號碼、或號碼被不同的人拿來填寫
    # 造成資料錯亂。用這支電話僅有那筆紀錄的姓名當作這支號碼「已登記」的姓名比對。
    if existing and existing["name"] != name:
        raise HTTPException(status_code=409, detail="此號碼已經註冊")

    # 同一天內同一支電話如果還有沒填完的草稿，接著用同一筆；隔天再來就當作是
    # 新的一次諮詢，不會撈到昨天以前放棄的草稿。
    if existing and existing["status"] == "in_progress" and is_same_local_day(existing["created_at"], now):
        update = {"name": name, "gender": gender, "answers.gender": gender}
        # 這次是從 LINE 連結進來的話，把 uid 補記到既有草稿上（第一次可能是
        # 直接開網址、沒帶 uid）；沒帶就保留原值，不要把已知的 uid 洗掉。
        if body.line_uid:
            update["line_uid"] = body.line_uid
        responses_col.update_one({"_id": existing["_id"]}, {"$set": update})
        doc = responses_col.find_one({"_id": existing["_id"]})
        result = _doc_to_response(doc)
        result["resumed"] = True
        result["prefilled"] = False
        return {"response": result}

    # 沒有可以接著填的草稿。如果這支電話僅有的那一筆是「已送出」，把答案帶過來
    # 當這次的初始值，讓顧客直接在上面修改，不用每次都從空白重新填一遍；接著
    # 用這次的內容覆蓋掉那一筆（有既有紀錄就更新，沒有才新增），不留舊資料。
    prior = existing if existing and existing["status"] == "submitted" else None
    initial_answers = {**prior["answers"], "gender": gender} if prior else {"gender": gender}
    # uid 沒帶就沿用既有紀錄上的值，不要把已知的 uid 洗掉。
    line_uid = body.line_uid or (existing.get("line_uid") if existing else None)

    fields = {
        "schema_id": str(active["_id"]),
        "name": name,
        "phone": body.phone,
        "gender": gender,
        "line_uid": line_uid,
        "status": "in_progress",
        "answers": initial_answers,
        "created_at": utc_now_iso(),
        "submitted_at": None,
    }
    if existing:
        responses_col.update_one({"_id": existing["_id"]}, {"$set": fields})
        doc = {**fields, "_id": existing["_id"]}
    else:
        insert_result = responses_col.insert_one(fields)
        doc = {**fields, "_id": insert_result.inserted_id}

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


@router.get("/responses/{response_id}")
def get_response(response_id: str):
    oid = _parse_object_id(response_id)
    doc = responses_col.find_one({"_id": oid})
    if doc is None:
        raise HTTPException(status_code=404, detail="Response not found")
    return {"response": _doc_to_response(doc)}
