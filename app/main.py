from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import expenses
from app.database import get_connection  # DB接続テストに必要

# --- FastAPIアプリ作成 ---
app = FastAPI(title="Expense Management App")

# --- CORS設定（フロント⇔API通信許可）---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",  # VSCode Live Server
        "http://localhost:5500",  # ローカルサーバー
        "http://127.0.0.1:8000",  # API自身
        "file://",                # ローカルHTML開発用
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- ルーター登録 ---
app.include_router(expenses.router, prefix="/api/expenses", tags=["Expenses"])

# --- ルート確認用 ---
@app.get("/")
def root():
    return {"message": "Expense Management API is running 🚀"}

# --- DB接続確認用 ---
@app.get("/test-db")
def test_db():
    """PostgreSQLに接続し、バージョンを返す簡易テスト"""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT version();")
    version = cur.fetchone()[0]
    cur.close()
    conn.close()
    return {"postgres_version": version}
