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

responses_col.create_index("phone")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_same_local_day(iso_str: str, reference: datetime) -> bool:
    dt = datetime.fromisoformat(iso_str)
    return dt.astimezone(LOCAL_TZ).date() == reference.astimezone(LOCAL_TZ).date()


def init_db() -> None:
    if schemas_col.count_documents({}) == 0:
        schemas_col.insert_one(
            {
                "version": SCHEMA_V1["version"],
                "steps": SCHEMA_V1["steps"],
                "is_active": True,
                "created_at": utc_now_iso(),
            }
        )
