import re
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from ..db import is_same_local_day, responses_col, schemas_col, utc_now_iso

router = APIRouter()

# 台灣手機號碼固定 09 開頭共 10 碼。前端已經有防呆（即時濾除非數字、格式檢查），
# 這裡是後端這層再擋一次，避免有人繞過前端直接打 API。
PHONE_PATTERN = re.compile(r"^09\d{8}$")


class CreateResponseBody(BaseModel):
    name: str = Field(min_length=1)
    phone: str = Field(min_length=1)
    gender: str = Field(min_length=1)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        v = v.strip()
        if not PHONE_PATTERN.match(v):
            raise ValueError("手機號碼格式不正確，需為 09 開頭的 10 碼數字")
        return v


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

    # 防呆：同一支電話不能對應到不同姓名，避免打錯號碼、或號碼被不同的人拿來填寫
    # 造成資料錯亂。用這支電話最近一筆紀錄的姓名當作這支號碼「已登記」的姓名比對。
    latest_for_phone = responses_col.find_one({"phone": body.phone}, sort=[("_id", -1)])
    if latest_for_phone and latest_for_phone["name"] != name:
        raise HTTPException(status_code=409, detail="此號碼已經註冊")

    # 同一天內同一支電話如果還有沒填完的草稿，接著用同一筆，不要疊出一堆填一半的
    # 重複紀錄；隔天再來就當作是新的一次諮詢，不會撈到昨天以前放棄的草稿。
    draft = responses_col.find_one({"phone": body.phone, "status": "in_progress"}, sort=[("_id", -1)])
    if draft and is_same_local_day(draft["created_at"], now):
        responses_col.update_one(
            {"_id": draft["_id"]},
            {"$set": {"name": name, "gender": gender, "answers.gender": gender}},
        )
        doc = responses_col.find_one({"_id": draft["_id"]})
        result = _doc_to_response(doc)
        result["resumed"] = True
        result["prefilled"] = False
        return {"response": result}

    # 沒有可以接著填的草稿，找這支電話最近一次「已送出」的資料，把答案帶過來當
    # 這次的初始值，讓顧客直接在上面修改，不用每次都從空白重新填一遍。
    prior = responses_col.find_one({"phone": body.phone, "status": "submitted"}, sort=[("submitted_at", -1)])
    initial_answers = {**prior["answers"], "gender": gender} if prior else {"gender": gender}

    doc = {
        "schema_id": str(active["_id"]),
        "name": name,
        "phone": body.phone,
        "gender": gender,
        "status": "in_progress",
        "answers": initial_answers,
        "created_at": utc_now_iso(),
        "submitted_at": None,
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
