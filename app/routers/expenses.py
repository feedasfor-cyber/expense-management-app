import os
import io
import csv
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from psycopg2.extras import Json
from app.database import get_connection
from app.utils.csv_validator import validate_csv

router = APIRouter()

# =====================================================
# 定数・初期設定
# =====================================================
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# =====================================================
# ① CSVアップロードAPI
# =====================================================
@router.post("/")
async def upload_expense_csv(file: UploadFile = File(...)):
    """CSVをアップロードしてDBに登録"""
    headers, rows = validate_csv(file)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = os.path.join(UPLOAD_DIR, f"{timestamp}_{file.filename}")

    with open(save_path, "wb") as f:
        f.write(await file.read())

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO expense_datasets (file_name, row_count, uploader, original_path)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
        """, (file.filename, len(rows), "admin", save_path))
        dataset_id = cur.fetchone()[0]

        for row in rows:
            cur.execute("""
                INSERT INTO expense_rows (dataset_id, row_data)
                VALUES (%s, %s);
            """, (dataset_id, Json(dict(zip(headers, row)))))

        conn.commit()

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"DBエラー: {e}")

    finally:
        cur.close()
        conn.close()

    return {
        "dataset_id": dataset_id,
        "row_count": len(rows),
        "file": file.filename,
        "status": "success"
    }


# =====================================================
# ② アップロード履歴API
# =====================================================
@router.get("/")
def list_expense_datasets():
    """アップロード履歴を取得"""
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


# =====================================================
# ③ 明細取得API（ページング＋検索）
# =====================================================
@router.get("/{dataset_id}")
def get_expense_details(
    dataset_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    filter_col: str = Query(None),
    filter_val: str = Query(None)
):
    """特定データセットの明細取得"""
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT id FROM expense_datasets WHERE id=%s;", (dataset_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

        where_clause = ""
        params = [dataset_id]
        if filter_col and filter_val:
            where_clause = "AND row_data ->> %s ILIKE %s"
            params.extend([filter_col, f"%{filter_val}%"])

        cur.execute(f"SELECT COUNT(*) FROM expense_rows WHERE dataset_id=%s {where_clause};", params)
        total = cur.fetchone()[0]

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
            "meta": {"dataset_id": dataset_id, "total_rows": total, "page": page, "page_size": size},
            "data": rows
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB query failed: {e}")

    finally:
        cur.close()
        conn.close()


# =====================================================
# ④ 元CSV再ダウンロードAPI
# =====================================================
@router.get("/{dataset_id}/download")
def download_expense_csv(dataset_id: int):
    """アップロード元CSVファイルをそのまま返却"""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT file_name, original_path
            FROM expense_datasets
            WHERE id = %s;
        """, (dataset_id,))
        record = cur.fetchone()
        if not record:
            raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

        file_name, path = record
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

        return FileResponse(
            path=path,
            filename=file_name,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{file_name}"'}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File download failed: {e}")

    finally:
        cur.close()
        conn.close()


# =====================================================
# ⑤ フィルタ付きCSVダウンロードAPI
# =====================================================
@router.get("/{dataset_id}/download_csv")
def download_filtered_csv(
    dataset_id: int,
    # --- 文字列 ---
    filter_col: list[str] = Query(None),
    filter_val: list[str] = Query(None),
    # --- 数値 ---
    num_col: list[str] = Query(None),
    num_op: list[str] = Query(None),
    num_val: list[str] = Query(None),
    # --- 日付 ---
    date_col: list[str] = Query(None),
    date_from: list[str] = Query(None),
    date_to: list[str] = Query(None)
):
    """文字列＋数値＋日付条件対応のフィルタ付きCSV出力"""
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT id FROM expense_datasets WHERE id=%s;", (dataset_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

        where_conditions = []
        params = [dataset_id]

        # (A) 文字列フィルタ（OR）
        if filter_col and filter_val:
            for col, val in zip(filter_col, filter_val):
                or_vals = [v.strip() for v in val.split(",") if v.strip()]
                conds = []
                for v in or_vals:
                    conds.append("row_data ->> %s ILIKE %s")
                    params.extend([col, f"%{v}%"])
                where_conditions.append("(" + " OR ".join(conds) + ")")

        # (B) 数値フィルタ
        if num_col and num_op and num_val:
            for col, op, val in zip(num_col, num_op, num_val):
                if op.lower() == "between":
                    min_v, max_v = map(float, val.split(","))
                    where_conditions.append("(CAST(row_data ->> %s AS NUMERIC) BETWEEN %s AND %s)")
                    params.extend([col, min_v, max_v])
                else:
                    ops = {"gt": ">", "lt": "<", "ge": ">=", "le": "<=", "eq": "="}
                    if op.lower() not in ops:
                        raise HTTPException(status_code=400, detail=f"無効な比較演算子: {op}")
                    where_conditions.append(f"(CAST(row_data ->> %s AS NUMERIC) {ops[op.lower()]} %s)")
                    params.extend([col, float(val)])

        # (C) 日付範囲フィルタ
        if date_col:
            max_len = len(date_col)
            date_from = (date_from or []) + [None] * (max_len - len(date_from or []))
            date_to   = (date_to or []) + [None] * (max_len - len(date_to or []))
            for col, start, end in zip(date_col, date_from, date_to):
                if start and end:
                    where_conditions.append("(CAST(row_data ->> %s AS DATE) BETWEEN %s AND %s)")
                    params.extend([col, start, end])
                elif start:
                    where_conditions.append("(CAST(row_data ->> %s AS DATE) >= %s)")
                    params.extend([col, start])
                elif end:
                    where_conditions.append("(CAST(row_data ->> %s AS DATE) <= %s)")
                    params.extend([col, end])

        where_clause = " AND ".join(where_conditions)
        if where_clause:
            where_clause = "AND " + where_clause

        # データ取得
        cur.execute(f"""
            SELECT row_data
            FROM expense_rows
            WHERE dataset_id=%s {where_clause}
            ORDER BY id;
        """, params)
        rows = [r[0] for r in cur.fetchall()]

        if not rows:
            raise HTTPException(status_code=404, detail="該当データが見つかりません。")

        # CSV生成
        headers = list(rows[0].keys())
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

        buffer.seek(0)
        filename = f"filtered_expenses_{dataset_id}.csv"

        return StreamingResponse(
            iter([buffer.getvalue().encode("utf-8-sig")]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CSV export failed: {e}")

    finally:
        cur.close()
        conn.close()
