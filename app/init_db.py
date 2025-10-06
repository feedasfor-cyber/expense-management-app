# app/init_db.py
from app.database import get_connection
from app.models import CREATE_TABLES_SQL

def init():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(CREATE_TABLES_SQL)
    conn.commit()
    cur.close()
    conn.close()
    print("✅ Tables created (if not exists).")

if __name__ == "__main__":
    init()
