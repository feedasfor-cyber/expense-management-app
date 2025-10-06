import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()  # .envファイルの読み込み

DATABASE_URL = os.getenv("DATABASE_URL")

def get_connection():
    """PostgreSQLへの接続を返す"""
    return psycopg2.connect(DATABASE_URL)
