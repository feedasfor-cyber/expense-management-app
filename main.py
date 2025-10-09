from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import text

# 🔐 認証用
from app.auth import basic_auth_middleware, basic_auth

# 📦 ルーター & DB
from app.routers import expenses
from app.db import get_db
from app.logger import logger

import logging

# ==========================
# ログ設定
# ==========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),                     # コンソール出力
        logging.FileHandler("app.log", encoding="utf-8")  # ファイル出力
    ]
)

logger = logging.getLogger(__name__)


# ============================
# 🚀 FastAPI アプリ作成
# ============================
app = FastAPI(title="Expense Management App")

# ============================
# 🧭 グローバル エラーハンドラー
# ============================
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

# ============================
# 🔐 Basic認証ミドルウェア（全API共通）
# ============================
app.middleware("http")(basic_auth_middleware)

# ============================
# 🌐 CORS設定（開発用）
# ============================
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

# ============================
# 🧾 ルーター登録
# ============================
app.include_router(expenses.router, prefix="/api/expenses", tags=["Expenses"])

# ============================
# 🏡 静的ファイル配信（frontend/index.html）
# ============================
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

# ============================
# 🧪 個別認証テスト用
# ============================
@app.get("/secure", dependencies=[Depends(basic_auth)])
def secure_endpoint():
    return {"message": "🔐 認証済みエンドポイント"}

# ============================
# 🧰 DB接続確認用
# ============================
@app.get("/test-db")
def test_db(db=Depends(get_db)):
    version = db.execute(text("SELECT version();")).scalar()
    return {"postgres_version": version}
