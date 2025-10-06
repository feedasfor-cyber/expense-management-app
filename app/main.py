from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import expenses
from app.database import get_connection  # ★ これが必須です！

# FastAPIアプリを作成
app = FastAPI(title="Expense Management App")

# CORS設定：他のドメイン（例：フロント側）からAPIを呼べるようにする
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # すべてのオリジンから許可（開発用）
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ルーター登録：app/routers/expenses.py のエンドポイントを統合
app.include_router(expenses.router, prefix="/api/expenses", tags=["Expenses"])

@app.get("/")
def root():
    return {"message": "Expense Management API is running 🚀"}

# ★ DB接続テスト用エンドポイント
@app.get("/test-db")
def test_db():
    """
    PostgreSQLに接続し、バージョンを返す簡易テスト。
    失敗したら例外となるため、接続の成否がすぐ分かる。
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT version();")
    version = cur.fetchone()[0]
    cur.close()
    conn.close()
    return {"postgres_version": version}
