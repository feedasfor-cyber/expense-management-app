from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import Column, Integer, ForeignKey, Text
import json

# ==========================
# 🧾 DB関連
# ==========================
from app.db import Base, engine, get_db
import app.models  # ✅ モデルを読み込む（これでテーブルが作成される）
Base.metadata.create_all(bind=engine)

# ==========================
# 🔐 認証
# ==========================
from app.auth import basic_auth_middleware, basic_auth

# ==========================
# 📦 ルーター
# ==========================
from app.routers import expenses

# ==========================
# 🪵 ログ
# ==========================
import logging
from app.logger import logger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

# ==========================
# 🚀 FastAPI アプリ作成
# ==========================
app = FastAPI(title="Expense Management App")

# ==========================
# 🧭 グローバル エラーハンドラー
# ==========================
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail or "An error occurred"},
    )

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": f"Internal Server Error: {str(exc)}"},
    )

# ==========================
# 🔐 Basic認証ミドルウェア
# ==========================
app.middleware("http")(basic_auth_middleware)

# ==========================
# 🌐 CORS設定
# ==========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:8000",
        "file://",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================
# 🧾 ルーター登録
# ==========================
app.include_router(expenses.router, prefix="/api/expenses", tags=["Expenses"])

# ==========================
# 🧪 認証テスト
# ==========================
@app.get("/secure", dependencies=[Depends(basic_auth)])
def secure_endpoint():
    return {"message": "🔐 認証済みエンドポイント"}

# ==========================
# 🧰 DB接続テスト
# ==========================
@app.get("/test-db")
def test_db(db=Depends(get_db)):
    try:
        version = db.execute(text("SELECT sqlite_version();")).scalar()
        return {"db_version": version}
    except Exception:
        version = db.execute(text("SELECT version();")).scalar()
        return {"db_version": version}

# ==========================
# 🏡 静的ファイル配信
# ==========================
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")