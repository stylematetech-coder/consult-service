from dotenv import load_dotenv

load_dotenv()  # 要在 .db 讀取 MONGO_URI 等環境變數之前先載入 .env

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from .db import init_db  # noqa: E402
from .routers import availability, responses, schema  # noqa: E402

app = FastAPI(title="consult-service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

app.include_router(schema.router)
app.include_router(responses.router)
app.include_router(availability.router)


@app.get("/health")
def health():
    return {"status": "ok"}
