import os
from datetime import datetime
import psycopg2
from psycopg2.extras import Json
from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse
from app.database import get_connection
from app.utils.csv_validator import validate_csv

router = APIRouter()

# アップロードファイル保存先
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# -------------------------------
# ① CSVアップロードAPI
# -------------------------------
@router.post("/")
async def upload_expense_csv(file: UploadFile = File(...)):
    """
    CSVアップロードAPI:
    1. CSVファイルを受け取る
    2. バリデーション
    3. uploads/ に保存
    4. DBに登録
    """
    # --- 1️⃣ CSVバリデーション ---
    headers, rows = validate_csv(file)

    # --- 2️⃣ ファイル保存 ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = os.path.join(UPLOAD_DIR, f"{timestamp}_{file.filename}")

    with open(save_path, "wb") as f:
        f.write(await file.read())

    # --- 3️⃣ DB登録 ---
    conn = get_connection()
    cur = conn.cursor()

    try:
        # datasetsテーブルに登録
        cur.execute("""
            INSERT INTO expense_datasets (file_name, row_count, uploader, original_path)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
        """, (file.filename, len(rows), "admin", save_path))
        dataset_id = cur.fetchone()[0]

        # 各行をJSON形式で保存
        for row in rows:
            row_dict = dict(zip(headers, row))
            cur.execute("""
                INSERT INTO expense_rows (dataset_id, row_data)
                VALUES (%s, %s);
            """, (dataset_id, Json(row_dict)))

        conn.commit()

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"DBエラー: {e}")

    finally:
        cur.close()
        conn.close()

    # --- 4️⃣ レスポンス ---
    return {
        "dataset_id": dataset_id,
        "row_count": len(rows),
        "file": file.filename,
        "status": "success"
    }


# -------------------------------
# ② 一覧API
# -------------------------------
@router.get("/")
def list_expense_datasets():
    """アップロード履歴一覧を取得"""
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT id, file_name, row_count, uploaded_at
            FROM expense_datasets
            ORDER BY uploaded_at DESC;
        """)
        records = cur.fetchall()

        result = [
            {
                "id": r[0],
                "file_name": r[1],
                "row_count": r[2],
                "uploaded_at": r[3].strftime("%Y-%m-%d %H:%M:%S")
            }
            for r in records
        ]

        return JSONResponse(content=result)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB query failed: {e}")

    finally:
        cur.close()
        conn.close()


# -------------------------------
# ③ 詳細API
# -------------------------------
@router.get("/{dataset_id}")
def get_expense_details(
    dataset_id: int,
    page: int = Query(1, ge=1, description="ページ番号"),
    size: int = Query(20, ge=1, le=100, description="1ページ件数"),
    filter_col: str = Query(None, description="フィルタ列名"),
    filter_val: str = Query(None, description="フィルタ条件")
):
    """特定のdataset_idの明細を取得（ページング＆フィルタ対応）"""
    conn = get_connection()
    cur = conn.cursor()

    try:
        # --- dataset存在確認 ---
        cur.execute("SELECT id FROM expense_datasets WHERE id=%s;", (dataset_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found.")

        # --- フィルタ条件 ---
        where_clause = ""
        params = [dataset_id]
        if filter_col and filter_val:
            where_clause = "AND row_data ->> %s ILIKE %s"
            params.extend([filter_col, f"%{filter_val}%"])

        # --- 総件数 ---
        cur.execute(f"SELECT COUNT(*) FROM expense_rows WHERE dataset_id=%s {where_clause};", params)
        total = cur.fetchone()[0]

        # --- ページング ---
        offset = (page - 1) * size
        cur.execute(f"""
            SELECT row_data
            FROM expense_rows
            WHERE dataset_id=%s {where_clause}
            ORDER BY id
            LIMIT %s OFFSET %s;
        """, params + [size, offset])
        rows = [r[0] for r in cur.fetchall()]

        return JSONResponse(content={
            "meta": {
                "dataset_id": dataset_id,
                "total_rows": total,
                "page": page,
                "page_size": size
            },
            "data": rows
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB query failed: {e}")

    finally:
        cur.close()
        conn.close()


# -------------------------------
# ④ 再ダウンロードAPI
# -------------------------------
@router.get("/{dataset_id}/download")
def download_expense_csv(dataset_id: int):
    """
    再ダウンロードAPI:
    - 指定された dataset_id の元CSVファイルを返す
    - Content-Disposition: attachment でブラウザ保存可能
    """
    conn = get_connection()
    cur = conn.cursor()

    try:
        # --- ファイル情報取得 ---
        cur.execute("""
            SELECT file_name, original_path
            FROM expense_datasets
            WHERE id = %s;
        """, (dataset_id,))
        record = cur.fetchone()

        if not record:
            raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

        file_name, original_path = record

        # --- ファイル存在チェック ---
        if not os.path.exists(original_path):
            raise HTTPException(status_code=404, detail=f"File not found: {original_path}")

        # --- FileResponseで返却 ---
        return FileResponse(
            path=original_path,
            filename=file_name,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{file_name}"'}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File download failed: {e}")

    finally:
        cur.close()
        conn.close()
