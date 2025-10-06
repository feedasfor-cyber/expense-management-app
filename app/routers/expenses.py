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
# 共通：フィルタSQL構築関数
# =====================================================
def build_filter_conditions(
    filter_col=None, filter_val=None,
    num_col=None, num_op=None, num_val=None,
    date_col=None, date_from=None, date_to=None,
    include_dataset_id: bool = False
):
    """共通フィルタSQL生成（WHERE/AND とパラメータ列を返す）"""
    where_conditions = []
    params = []

    # 文字列フィルタ（OR）
    if filter_col and filter_val:
        for col, val in zip(filter_col, filter_val):
            or_vals = [v.strip() for v in val.split(",") if v.strip()]
            conds = []
            for v in or_vals:
                conds.append("row_data ->> %s ILIKE %s")
                params.extend([col, f"%{v}%"])
            if conds:
                where_conditions.append("(" + " OR ".join(conds) + ")")

    # 数値フィルタ
    if num_col and num_op and num_val:
        for col, op, val in zip(num_col, num_op, num_val):
            if op and op.lower() == "between":
                min_v, max_v = map(float, val.split(","))
                where_conditions.append("(CAST(row_data ->> %s AS NUMERIC) BETWEEN %s AND %s)")
                params.extend([col, min_v, max_v])
            else:
                ops = {"gt": ">", "lt": "<", "ge": ">=", "le": "<=", "eq": "="}
                if not op or op.lower() not in ops:
                    raise HTTPException(status_code=400, detail=f"無効な比較演算子: {op}")
                where_conditions.append(f"(CAST(row_data ->> %s AS NUMERIC) {ops[op.lower()]} %s)")
                params.extend([col, float(val)])

    # 日付フィルタ
    if date_col:
        max_len = len(date_col)
        date_from = (date_from or []) + [None] * (max_len - len(date_from or []))
        date_to   = (date_to   or []) + [None] * (max_len - len(date_to   or []))
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
        where_clause = ("AND " if include_dataset_id else "WHERE ") + where_clause

    return where_clause, params

# =====================================================
# ① 全データセット横断API（CSV / JSON）
# =====================================================
def query_all_filtered_rows(cur, **filters):
    """共通：全データセット横断検索"""
    where_clause, params = build_filter_conditions(**filters)
    cur.execute(f"SELECT row_data FROM expense_rows {where_clause} ORDER BY dataset_id, id;", params)
    return [r[0] for r in cur.fetchall()]

@router.get("/download_all_csv")
def download_all_filtered_csv(
    filter_col: list[str] = Query(None),
    filter_val: list[str] = Query(None),
    num_col: list[str] = Query(None),
    num_op: list[str] = Query(None),
    num_val: list[str] = Query(None),
    date_col: list[str] = Query(None),
    date_from: list[str] = Query(None),
    date_to: list[str] = Query(None),
):
    """全データセット横断のCSV出力"""
    conn = get_connection(); cur = conn.cursor()
    try:
        where_clause, params = build_filter_conditions(
            filter_col, filter_val, num_col, num_op, num_val,
            date_col, date_from, date_to, include_dataset_id=False
        )
        cur.execute(f"SELECT row_data FROM expense_rows {where_clause} ORDER BY dataset_id, id;", params)
        rows = [r[0] for r in cur.fetchall()]
        if not rows:
            raise HTTPException(status_code=404, detail="該当データなし")

        headers = list(rows[0].keys())
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=headers)
        writer.writeheader(); writer.writerows(rows); buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue().encode("utf-8-sig")]),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="all_filtered_expenses.csv"'}
        )
    finally:
        cur.close(); conn.close()

@router.get("/download_all_json")
def download_all_filtered_json(
    filter_col: list[str] = Query(None),
    filter_val: list[str] = Query(None),
    num_col: list[str] = Query(None),
    num_op: list[str] = Query(None),
    num_val: list[str] = Query(None),
    date_col: list[str] = Query(None),
    date_from: list[str] = Query(None),
    date_to: list[str] = Query(None),
):
    """全データセット横断のJSON出力（フロントのプレビュー用）"""
    conn = get_connection(); cur = conn.cursor()
    try:
        rows = query_all_filtered_rows(
            cur,
            filter_col=filter_col, filter_val=filter_val,
            num_col=num_col, num_op=num_op, num_val=num_val,
            date_col=date_col, date_from=date_from, date_to=date_to
        )
        return {"total": len(rows), "data": rows}
    finally:
        cur.close(); conn.close()

# =====================================================
# ② CSVアップロードAPI
# =====================================================
@router.post("/")
async def upload_expense_csv(file: UploadFile = File(...)):
    """CSVをアップロードしてDBに登録"""
    headers, rows = validate_csv(file)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = os.path.join(UPLOAD_DIR, f"{timestamp}_{file.filename}")
    with open(save_path, "wb") as f:
        f.write(await file.read())

    conn = get_connection(); cur = conn.cursor()
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
        cur.close(); conn.close()

    return {"dataset_id": dataset_id, "row_count": len(rows), "file": file.filename, "status": "success"}

# =====================================================
# ③ アップロード履歴API
# =====================================================
@router.get("/")
def list_expense_datasets():
    """アップロード履歴を取得"""
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, file_name, row_count, uploaded_at
            FROM expense_datasets
            ORDER BY uploaded_at DESC;
        """)
        result = [
            {
                "id": r[0],
                "file_name": r[1],
                "row_count": r[2],
                "uploaded_at": r[3].strftime("%Y-%m-%d %H:%M:%S"),
            }
            for r in cur.fetchall()
        ]
        return JSONResponse(content=result)
    finally:
        cur.close(); conn.close()

# =====================================================
# ④ 明細取得API（ページング＋検索）
# =====================================================
@router.get("/{dataset_id}")
def get_expense_details(
    dataset_id: int,
    page: int = 1,
    size: int = 20,
    filter_col: str | None = None,
    filter_val: str | None = None,
):
    """特定データセットの明細取得"""
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM expense_datasets WHERE id=%s;", (dataset_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

        where_clause, params = "", [dataset_id]
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

        return {"meta": {"total_rows": total, "page": page, "page_size": size}, "data": rows}
    finally:
        cur.close(); conn.close()

# =====================================================
# ⑤ 元CSV再ダウンロードAPI
# =====================================================
@router.get("/{dataset_id}/download")
def download_expense_csv(dataset_id: int):
    """アップロード元CSVファイルをそのまま返却"""
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT file_name, original_path FROM expense_datasets WHERE id=%s;", (dataset_id,))
        record = cur.fetchone()
        if not record:
            raise HTTPException(status_code=404, detail="Dataset not found")

        file_name, path = record
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

        return FileResponse(path, filename=file_name, media_type="text/csv")
    finally:
        cur.close(); conn.close()

# =====================================================
# ⑥ フィルタ付きCSV出力（単一データセット）
# =====================================================
@router.get("/{dataset_id}/download_csv")
def download_filtered_csv(
    dataset_id: int,
    filter_col: list[str] = Query(None),
    filter_val: list[str] = Query(None),
    num_col: list[str] = Query(None),
    num_op: list[str] = Query(None),
    num_val: list[str] = Query(None),
    date_col: list[str] = Query(None),
    date_from: list[str] = Query(None),
    date_to: list[str] = Query(None),
):
    """単一データセットの条件付きCSV出力"""
    conn = get_connection(); cur = conn.cursor()
    try:
        where_clause, params = build_filter_conditions(
            filter_col, filter_val, num_col, num_op, num_val,
            date_col, date_from, date_to, include_dataset_id=True
        )
        cur.execute(f"""
            SELECT row_data FROM expense_rows
            WHERE dataset_id=%s {where_clause}
            ORDER BY id;
        """, [dataset_id] + params)
        rows = [r[0] for r in cur.fetchall()]
        if not rows:
            raise HTTPException(status_code=404, detail="No data found")

        headers = list(rows[0].keys())
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=headers)
        writer.writeheader(); writer.writerows(rows); buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue().encode("utf-8-sig")]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="filtered_{dataset_id}.csv"'}
        )
    finally:
        cur.close(); conn.close()
