import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from pymongo import MongoClient
from pymongo.collection import Collection

from .question_schema_v1 import SCHEMA_V1

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.environ.get("MONGO_DB", "consult_service")

# 用來判斷「未完成草稿是不是同一個營業日」，門市在台灣，用台北時區判斷「同一天」
# 才會符合現場的認知，不能直接比 UTC 日期（會在午夜前後差一個時區的時間差到）。
LOCAL_TZ = ZoneInfo("Asia/Taipei")

_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
_db = _client[MONGO_DB_NAME]

schemas_col: Collection = _db["questionnaire_schemas"]
responses_col: Collection = _db["responses"]

# 2026-08-03 下午推翻同日上午的決定:一支電話/一個客人可以有多筆表單(不同天
# 做不同服務),所以 phone 不再是唯一鍵——一人多筆是常態,不是例外。索引留著
# (非唯一)純粹是給「設計師查詢」那支依電話查詢的效能用。真正拿來分辨「這些
# 表單是不是同一位客人的」是 line_uid,不是 phone(電話是客人自己講的話,任何
# 人都講得出別人的電話;line_uid 是 LINE 平台驗證過的身分)。
responses_col.create_index("phone")
# 給「我的表單」列表頁(GET /responses/mine)用,同樣非唯一——一個 line_uid
# 本來就會對應多筆表單。
responses_col.create_index("line_uid")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_same_local_day(iso_str: str, reference: datetime) -> bool:
    dt = datetime.fromisoformat(iso_str)
    return dt.astimezone(LOCAL_TZ).date() == reference.astimezone(LOCAL_TZ).date()


def init_db() -> None:
    # Schema 是不可變版本：舊回覆仍透過 schema_id 查得到當時的題目；程式帶入新
    # version 時才建立並切換 active，重啟同一版不會重複插入。
    current = schemas_col.find_one({"version": SCHEMA_V1["version"]})
    if current is None:
        schemas_col.update_many({"is_active": True}, {"$set": {"is_active": False}})
        schemas_col.insert_one(
            {
                "version": SCHEMA_V1["version"],
                "steps": SCHEMA_V1["steps"],
                "is_active": True,
                "created_at": utc_now_iso(),
            }
        )
    elif not current.get("is_active"):
        schemas_col.update_many({"is_active": True}, {"$set": {"is_active": False}})
        schemas_col.update_one({"_id": current["_id"]}, {"$set": {"is_active": True}})
