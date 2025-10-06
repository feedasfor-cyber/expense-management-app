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
    """WHERE句＋パラメータリストを生成"""
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
        ops = {"gt": ">", "lt": "<", "ge": ">=", "le": "<=", "eq": "="}
        for col, op, val in zip(num_col, num_op, num_val):
            if op.lower() == "between":
                min_v, max_v = map(float, val.split(","))
                where_conditions.append("(CAST(row_data ->> %s AS NUMERIC) BETWEEN %s AND %s)")
                params.extend([col, min_v, max_v])
            elif op.lower() in ops:
                where_conditions.append(f"(CAST(row_data ->> %s AS NUMERIC) {ops[op.lower()]} %s)")
                params.extend([col, float(val)])
            else:
                raise HTTPException(status_code=400, detail=f"無効な比較演算子: {op}")

    # 日付フィルタ
    if date_col:
        for col, start, end in zip(
            date_col,
            (date_from or []) + [None] * (len(date_col) - len(date_from or [])),
            (date_to or []) + [None] * (len(date_col) - len(date_to or [])),
        ):
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
# ① 全データセット横断（CSV）
# =====================================================
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
    conn = get_connection(); cur = conn.cursor()
    try:
        where_clause, params = build_filter_conditions(
            filter_col, filter_val, num_col, num_op, num_val,
            date_col, date_from, date_to
        )
        cur.execute(f"SELECT row_data FROM expense_rows {where_clause} ORDER BY dataset_id, id;", params)
        rows = [r[0] for r in cur.fetchall()]
        if not rows:
            raise HTTPException(status_code=404, detail="該当データなし")

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader(); writer.writerows(rows)
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue().encode("utf-8-sig")]),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="all_filtered_expenses.csv"'}
        )
    finally:
        cur.close(); conn.close()


# =====================================================
# ② 全データセット横断（JSONプレビュー）
# =====================================================
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
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
):
    conn = get_connection(); cur = conn.cursor()
    try:
        where_clause, params = build_filter_conditions(
            filter_col, filter_val, num_col, num_op, num_val,
            date_col, date_from, date_to
        )
        cur.execute(f"SELECT COUNT(*) FROM expense_rows {where_clause};", params)
        total = cur.fetchone()[0]
        offset = (page - 1) * size
        cur.execute(
            f"SELECT row_data FROM expense_rows {where_clause} ORDER BY dataset_id, id LIMIT %s OFFSET %s;",
            params + [size, offset]
        )
        rows = [r[0] for r in cur.fetchall()]
        return {"meta": {"total": total, "page": page, "size": size}, "data": rows}
    finally:
        cur.close(); conn.close()


# =====================================================
# ③ CSVアップロード
# =====================================================
@router.post("/")
async def upload_expense_csv(file: UploadFile = File(...)):
    print("==== [UPLOAD START] ====")
    print(f"📂 ファイル名: {file.filename}")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="空ファイルです")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = os.path.join(UPLOAD_DIR, f"{timestamp}_{file.filename}")
    with open(save_path, "wb") as f:
        f.write(raw)
    print(f"✅ 保存: {save_path}")

    pseudo = io.BytesIO(raw)
    headers, rows = validate_csv(pseudo)
    print(f"✅ CSV検証完了: {len(rows)}行")

    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO expense_datasets (file_name, row_count, uploader, original_path)
            VALUES (%s, %s, %s, %s)
            RETURNING id, uploaded_at;
        """, (file.filename, len(rows), "admin", save_path))
        dataset_id, uploaded_at = cur.fetchone()

        for row in rows:
            cur.execute("INSERT INTO expense_rows (dataset_id, row_data) VALUES (%s, %s);",
                        (dataset_id, Json(dict(zip(headers, row)))))

        conn.commit()
        print(f"✅ 登録完了: dataset_id={dataset_id}")

        return {
            "status": "success",
            "dataset_id": dataset_id,
            "uploaded_at": uploaded_at.strftime("%Y-%m-%d %H:%M:%S") if uploaded_at else None,
            "row_count": len(rows),
            "file": file.filename,
            "saved_path": save_path
        }
    except Exception as e:
        conn.rollback()
        print("❌ DBエラー:", e)
        raise HTTPException(status_code=500, detail=f"DBエラー: {e}")
    finally:
        cur.close(); conn.close()
        print("==== [UPLOAD END] ====")


# =====================================================
# ④ アップロード履歴
# =====================================================
@router.get("/")
def list_expense_datasets():
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, file_name, row_count, uploaded_at
            FROM expense_datasets
            ORDER BY uploaded_at DESC;
        """)
        rows = cur.fetchall()
        result = [
            {
                "id": r[0],
                "file_name": r[1],
                "row_count": r[2],
                "uploaded_at": r[3].strftime("%Y-%m-%d %H:%M:%S") if r[3] else None
            }
            for r in rows
        ]
        print(f"[HISTORY] {len(result)} datasets loaded")
        return JSONResponse(content=result)
    finally:
        cur.close(); conn.close()

# =====================================================
# ⑤ 明細取得（特定データセットごと）
# =====================================================
@router.get("/{dataset_id}")
def get_expense_details(
    dataset_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """指定したデータセットの明細を返す（ページング対応）"""
    conn = get_connection()
    cur = conn.cursor()
    try:
        # 存在確認
        cur.execute("SELECT 1 FROM expense_datasets WHERE id=%s;", (dataset_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

        # 総件数
        cur.execute("SELECT COUNT(*) FROM expense_rows WHERE dataset_id=%s;", (dataset_id,))
        total = cur.fetchone()[0]

        # ページング取得
        offset = (page - 1) * size
        cur.execute("""
            SELECT row_data
            FROM expense_rows
            WHERE dataset_id=%s
            ORDER BY id
            LIMIT %s OFFSET %s;
        """, (dataset_id, size, offset))
        rows = [r[0] for r in cur.fetchall()]

        return {
            "meta": {"dataset_id": dataset_id, "total": total, "page": page, "size": size},
            "data": rows
        }
    finally:
        cur.close()
        conn.close()



# =====================================================
# ⑤ 元CSV再ダウンロード
# =====================================================
@router.get("/{dataset_id}/download")
def download_expense_csv(dataset_id: int):
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT file_name, original_path FROM expense_datasets WHERE id=%s;", (dataset_id,))
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="Dataset not found")
        file_name, path = r
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail=f"File not found: {path}")
        return FileResponse(path, filename=file_name, media_type="text/csv")
    finally:
        cur.close(); conn.close()


# =====================================================
# ⑥ デバッグAPI（DB接続情報＋件数）
# =====================================================
@router.get("/_debug/dbinfo")
def debug_dbinfo():
    from urllib.parse import urlparse
    db_url = os.getenv("DATABASE_URL")
    parsed = urlparse(db_url)
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM expense_datasets;")
        count = cur.fetchone()[0]
    finally:
        cur.close(); conn.close()
    return {
        "db": parsed.path.lstrip("/"),
        "host": parsed.hostname,
        "port": parsed.port,
        "expense_datasets_count": count
    }
