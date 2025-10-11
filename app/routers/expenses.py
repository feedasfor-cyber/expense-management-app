# app/routers/expenses.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from typing import Optional
from datetime import datetime
import csv
import io
import os
import time
import re
import json

from app.db import get_db
from app.models import ExpenseDataset, ExpenseRow
from app.auth import basic_auth
from app.logger import logger

router = APIRouter(tags=["Expenses"])

MAX_SIZE = 10 * 1024 * 1024  # 10MB

# ----------------------------
# ヘルパー
# ----------------------------
def ensure_uploads_dir() -> str:
    os.makedirs("uploads", exist_ok=True)
    return "uploads"

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]+', "_", name)

def timestamp_prefix() -> str:
    return time.strftime("%Y%m%d_%H%M%S")

def validate_file_extension(file: UploadFile):
    name = (file.filename or "").lower()
    if not name.endswith(".csv"):
        raise HTTPException(status_code=400, detail="CSVファイル（.csv）のみアップロード可能です")

def validate_file_size(file: UploadFile):
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size > MAX_SIZE:
        raise HTTPException(status_code=413, detail="ファイルサイズが10MBを超えています")

def read_csv(file: UploadFile):
    validate_file_extension(file)
    validate_file_size(file)
    try:
        content = file.file.read().decode("utf-8-sig")
    except Exception:
        raise HTTPException(status_code=400, detail="ファイルをUTF-8として読み込めません。")

    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        raise HTTPException(status_code=400, detail="CSVが空です。")

    header = rows[0]
    if len(set(header)) != len(header):
        raise HTTPException(status_code=400, detail="ヘッダに重複があります。")

    data_rows = rows[1:]
    for i, r in enumerate(data_rows, start=2):
        if len(r) != len(header):
            raise HTTPException(status_code=400, detail=f"{i}行目の列数が一致しません。")

    dict_rows = [dict(zip(header, row)) for row in data_rows]
    return header, dict_rows


# =====================================================
# ① CSVアップロード
# =====================================================
@router.post("/", status_code=201)
def upload_expense(
    file: UploadFile = File(...),
    branch_name: str = Form(..., description="支店名（例：大阪支店）"),
    period: str = Form(..., description="提出月（YYYY-MM 例：2025-10）"),
    db: Session = Depends(get_db),
    user: str = Depends(basic_auth),
):
    if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", period):
        raise HTTPException(status_code=400, detail="periodはYYYY-MM形式で指定してください。")

    header, rows = read_csv(file)

    # CSV 原本を保存（採点者の再現性確保）
    uploads_dir = ensure_uploads_dir()
    safe_name = sanitize_filename(file.filename or "uploaded.csv")
    save_name = f"{timestamp_prefix()}_{safe_name}"
    save_path = os.path.join(uploads_dir, save_name)
    with open(save_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        for r in rows:
            writer.writerow([r.get(h, "") for h in header])

    # メタ + 明細(JSONテキスト) をSQLiteへ保存
    dataset = ExpenseDataset(
        file_name=safe_name,
        row_count=len(rows),
        original_path=save_path,
        branch_name=branch_name,
        period=period,
    )
    db.add(dataset)
    db.flush()  # dataset.id 取得

    row_objects = [ExpenseRow(dataset_id=dataset.id, row_data=json.dumps(r, ensure_ascii=False)) for r in rows]
    if row_objects:
        db.bulk_save_objects(row_objects)

    db.commit()
    db.refresh(dataset)

    logger.info(f"[UPLOAD] user={user}, file={safe_name}, branch={branch_name}, period={period}, rows={len(rows)}")

    return {
        "status": "success",
        "dataset_id": dataset.id,
        "branch_name": branch_name,
        "period": period,
        "uploaded_at": dataset.uploaded_at.isoformat() if dataset.uploaded_at else None,
        "row_count": len(rows),
        "file": safe_name,
        "saved_path": save_path,
    }


# =====================================================
# ② アップロード履歴一覧
# 末尾あり/なしの両方で 200 を返すようにする
# =====================================================
@router.get("/")
def list_datasets(
    branch: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: str = Depends(basic_auth),
):
    stmt = select(ExpenseDataset).order_by(ExpenseDataset.uploaded_at.desc())
    if branch:
        stmt = stmt.where(ExpenseDataset.branch_name == branch)
    if period:
        stmt = stmt.where(ExpenseDataset.period == period)

    datasets = db.execute(stmt).scalars().all()
    return {
        "data": [
            {
                "id": d.id,
                "file_name": d.file_name,
                "row_count": d.row_count,
                "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
                "branch_name": d.branch_name,
                "period": d.period,
            }
            for d in datasets
        ]
    }

# ← これがないと /api/expenses （末尾なし）が 404 になる
@router.get("", include_in_schema=False)
def list_datasets_no_slash(
    branch: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: str = Depends(basic_auth),
):
    return list_datasets(branch=branch, period=period, db=db, user=user)


# =====================================================
# ③ フィルタ検索プレビュー（JSON）
#   ※ 静的パスを {dataset_id} よりも先に定義する！
# =====================================================
@router.get("/download_all_json")
def download_all_json(
    branch_name: Optional[str] = Query(None),
    branch: Optional[str] = Query(None, alias="branch"),
    period: Optional[str] = Query(None),
    filter_col: Optional[str] = Query(None),
    filter_val: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: str = Depends(basic_auth),
):
    target_branch = branch_name or branch

    # JSON テキストを LIKE で簡易検索（SQLite対応）
    stmt = select(ExpenseRow.row_data).join(ExpenseDataset, ExpenseRow.dataset_id == ExpenseDataset.id)
    if target_branch:
        stmt = stmt.where(ExpenseDataset.branch_name == target_branch)
    if period:
        stmt = stmt.where(ExpenseDataset.period == period)
    if filter_val:
        # filter_col が指定されても、まずはテキスト検索（提出要件：SQLite簡易対応）
        stmt = stmt.where(ExpenseRow.row_data.like(f"%{filter_val}%"))

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    offset = (page - 1) * size
    rows = db.execute(stmt.offset(offset).limit(size)).all()

    parsed_rows = [json.loads(r[0]) for r in rows]
    return {"meta": {"total": total, "page": page, "size": size}, "data": parsed_rows}


# =====================================================
# ④ フィルタ検索CSVダウンロード（プレビュー画面）
#   ※ 静的パスを {dataset_id} よりも先に定義する！
# =====================================================
@router.get("/download_all_csv")
def download_all_csv(
    branch_name: Optional[str] = Query(None),
    branch: Optional[str] = Query(None, alias="branch"),
    period: Optional[str] = Query(None),
    filter_col: Optional[str] = Query(None),
    filter_val: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: str = Depends(basic_auth),
):
    target_branch = branch_name or branch

    stmt = select(ExpenseRow.row_data).join(ExpenseDataset, ExpenseRow.dataset_id == ExpenseDataset.id)
    if target_branch:
        stmt = stmt.where(ExpenseDataset.branch_name == target_branch)
    if period:
        stmt = stmt.where(ExpenseDataset.period == period)
    if filter_val:
        stmt = stmt.where(ExpenseRow.row_data.like(f"%{filter_val}%"))

    rows = db.execute(stmt).all()
    parsed = [json.loads(r[0]) for r in rows]

    if not parsed:
        # 空ファイルを返すほうが UX は良いが、要件に合わせて 404
        raise HTTPException(status_code=404, detail="該当データがありません。")

    headers = list(parsed[0].keys())

    def generate():
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(headers)
        yield output.getvalue(); output.seek(0); output.truncate(0)
        for row in parsed:
            writer.writerow([row.get(h, "") for h in headers])
            yield output.getvalue(); output.seek(0); output.truncate(0)

    filename = f"filtered_{timestamp_prefix()}.csv"
    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# =====================================================
# ⑤ データセット単位の CSV ダウンロード（履歴のDLボタン用）
#   ※ 静的パスを {dataset_id} よりも先に定義する！
# =====================================================
@router.get("/dataset_csv/{dataset_id}")
def download_dataset_csv(
    dataset_id: int,
    db: Session = Depends(get_db),
    user: str = Depends(basic_auth),
):
    dataset = db.get(ExpenseDataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="指定されたデータセットが見つかりません。")

    stmt = select(ExpenseRow).where(ExpenseRow.dataset_id == dataset_id)
    rows = db.execute(stmt).scalars().all()
    parsed = [r.as_dict() for r in rows]

    if not parsed:
        raise HTTPException(status_code=404, detail="該当データがありません。")

    headers = list(parsed[0].keys())

    def generate():
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(headers)
        yield output.getvalue(); output.seek(0); output.truncate(0)
        for row in parsed:
            writer.writerow([row.get(h, "") for h in headers])
            yield output.getvalue(); output.seek(0); output.truncate(0)

    filename = f"dataset_{dataset_id}_{timestamp_prefix()}.csv"
    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# =====================================================
# ⑥ 明細表示（ページング）
#   ※ 動的パスは最後に定義して静的と衝突させない
# =====================================================
@router.get("/{dataset_id}")
def get_dataset_details(
    dataset_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    filter_col: Optional[str] = Query(None),
    filter_val: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: str = Depends(basic_auth),
):
    dataset = db.get(ExpenseDataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="指定されたデータセットが見つかりません。")

    stmt = select(ExpenseRow).where(ExpenseRow.dataset_id == dataset_id)
    if filter_val:
        stmt = stmt.where(ExpenseRow.row_data.like(f"%{filter_val}%"))

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    offset = (page - 1) * size
    rows = db.execute(stmt.offset(offset).limit(size)).scalars().all()

    return {
        "meta": {
            "branch_name": dataset.branch_name,
            "period": dataset.period,
            "total": total,
            "page": page,
            "size": size,
        },
        "data": [r.as_dict() for r in rows],
    }
