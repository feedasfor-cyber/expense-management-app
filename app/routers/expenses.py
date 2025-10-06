from fastapi import APIRouter, UploadFile, HTTPException
import csv, io
from app.database import get_connection

router = APIRouter()

@router.post("/")
async def upload_expense_csv(file: UploadFile):
    """CSVファイルをアップロードし、DBに保存する"""
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="CSVファイルのみ対応しています。")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="10MBを超えるファイルはアップロードできません。")

    reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
    rows = list(reader)
    if not rows:
        raise HTTPException(status_code=400, detail="CSVが空です。")

    conn = get_connection()
    cur = conn.cursor()

    # ファイル情報をdatasetsに登録
    cur.execute(
        "INSERT INTO expense_datasets (file_name, row_count, uploader, original_path) VALUES (%s,%s,%s,%s) RETURNING id",
        (file.filename, len(rows), "admin", file.filename)
    )
    dataset_id = cur.fetchone()[0]

    # 各行をexpense_rowsに登録
    for row in rows:
        cur.execute(
            "INSERT INTO expense_rows (dataset_id, row_data) VALUES (%s,%s)",
            (dataset_id, str(row))
        )

    conn.commit()
    conn.close()

    return {"dataset_id": dataset_id, "row_count": len(rows)}
