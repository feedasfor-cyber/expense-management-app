# app/db.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# .env の読み込み
load_dotenv()

# .env から DATABASE_URL を取得
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    # もし .env が無い or 変数が設定されていない場合は SQLite にフォールバック
    DATABASE_URL = "sqlite:///./app.db"

# SQLite の場合だけ check_same_thread=False を付与
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

# SQLAlchemy エンジンを作成
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True  # 長時間放置でも接続を健全に保つ設定
)

# セッション設定
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# モデルのベースクラス
Base = declarative_base()

# 依存関数（FastAPIのDependsで利用）
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
