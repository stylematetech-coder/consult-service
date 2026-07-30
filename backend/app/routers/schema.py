from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException

from ..db import schemas_col

router = APIRouter()


def _doc_to_schema(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "version": doc["version"],
        "is_active": doc["is_active"],
        "created_at": doc["created_at"],
        "steps": doc["steps"],
    }


@router.get("/schema/active")
def get_active_schema():
    doc = schemas_col.find_one({"is_active": True}, sort=[("_id", -1)])
    if doc is None:
        raise HTTPException(status_code=404, detail="No active schema found")
    return {"schema": _doc_to_schema(doc)}


@router.get("/schema/{schema_id}")
def get_schema(schema_id: str):
    try:
        oid = ObjectId(schema_id)
    except InvalidId:
        raise HTTPException(status_code=404, detail="Schema not found")
    doc = schemas_col.find_one({"_id": oid})
    if doc is None:
        raise HTTPException(status_code=404, detail="Schema not found")
    return {"schema": _doc_to_schema(doc)}
