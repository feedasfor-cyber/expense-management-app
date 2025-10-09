from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from datetime import datetime
from typing import Optional
import csv
import io
import os
import time
import re

from app.db import get_db
from app.models import ExpenseDataset, ExpenseRow
from app.auth import basic_auth  # 🔐 Basic認証
from app.utils.csv_validator import validate_csv  # （任意、今後の拡張用）
from app.logger import logger

router = APIRouter(tags=["expenses"])

# =====================================================
# 🧩 ヘルパー関数
# =====================================================

MAX_SIZE = 10 * 1024 * 1024  # 10MB上限

def ensure_uploads_dir():
    os.makedirs("uploads", exist_ok=True)
    return "uploads"

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]+', "_", name)

def timestamp_prefix() -> str:
    return time.strftime("%Y%m%d_%H%M%S")

def validate_file_extension(file: UploadFile):
    """拡張子が .csv かどうかチェック"""
    filename = file.filename or ""
    if not filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="CSVファイル（.csv）のみアップロード可能です"
        )

def validate_file_size(file: UploadFile):
    """10MB超過チェック"""
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size > MAX_SIZE:
        raise HTTPException(
            status_code=413,
            detail="ファイルサイズが10MBを超えています"
        )

def read_csv(file: UploadFile):
    """CSV内容の検証"""
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

    return header, [dict(zip(header, row)) for row in data_rows]


# =====================================================
# ① CSVアップロード
# =====================================================
@router.post("/", status_code=201)
def upload_expense(
    file: UploadFile = File(...),
    branch_name: str = Form(..., description="支店名（例：大阪支店）"),
    period: str = Form(..., description="提出月（YYYY-MM形式 例：2025-10）"),
    db: Session = Depends(get_db),
    user: str = Depends(basic_auth),
):
    # 📅 期間フォーマットチェック
    if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", period):
        raise HTTPException(
            status_code=400,
            detail="periodはYYYY-MM形式で指定してください。"
        )

    # 📄 CSVチェック（拡張子・サイズ・構造）
    header, rows = read_csv(file)

    # 🗂️ 保存処理
    uploads_dir = ensure_uploads_dir()
    safe_name = sanitize_filename(file.filename)
    save_name = f"{timestamp_prefix()}_{safe_name}"
    save_path = os.path.join(uploads_dir, save_name)

    with open(save_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for r in rows:
            writer.writerow(r.values())

    # 📝 DB登録
    dataset = ExpenseDataset(
        file_name=safe_name,
        row_count=len(rows),
        original_path=save_path,
        branch_name=branch_name,
        period=period,
    )
    db.add(dataset)
    db.flush()
    db.bulk_save_objects([ExpenseRow(dataset_id=dataset.id, row_data=r) for r in rows])
    db.commit()
    db.refresh(dataset)

    logger.info(f"[UPLOAD SUCCESS] user={user}, file={safe_name}, branch={branch_name}, period={period}, rows={len(rows)}")

    return {
        "status": "success",
        "dataset_id": dataset.id,
        "branch_name": branch_name,
        "period": period,
        "uploaded_at": str(dataset.uploaded_at),
        "row_count": len(rows),
        "file": safe_name,
        "saved_path": save_path,
    }


# =====================================================
# ② アップロード履歴一覧
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
                "uploaded_at": str(d.uploaded_at),
                "branch_name": d.branch_name,
                "period": d.period,
            }
            for d in datasets
        ]
    }


@router.get("", include_in_schema=False)
def list_datasets_no_trailing_slash(
    branch: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    return list_datasets(branch=branch, period=period, db=db)


# =====================================================
# ③ 横断JSONプレビュー
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
    stmt = select(ExpenseRow.row_data).join(ExpenseDataset, ExpenseRow.dataset_id == ExpenseDataset.id)

    if target_branch:
        stmt = stmt.where(ExpenseDataset.branch_name == target_branch)
    if period:
        stmt = stmt.where(ExpenseDataset.period == period)
    if filter_col and filter_val:
        stmt = stmt.where(ExpenseRow.row_data[filter_col].astext.ilike(f"%{filter_val}%"))

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    offset = (page - 1) * size
    rows = db.execute(stmt.offset(offset).limit(size)).all()

    return {"meta": {"total": total, "page": page, "size": size}, "data": [r[0] for r in rows]}


# =====================================================
# ④ 横断CSVダウンロード
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
    if filter_col and filter_val:
        stmt = stmt.where(ExpenseRow.row_data[filter_col].astext.ilike(f"%{filter_val}%"))

    def generate():
        rows = db.execute(stmt).all()
        if not rows:
            yield ""
            return
        header = list(rows[0][0].keys())
        sio = io.StringIO()
        writer = csv.writer(sio, lineterminator="\n")
        writer.writerow(header)
        for r in rows:
            writer.writerow([r[0].get(h, "") for h in header])
        yield sio.getvalue()

    filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# =====================================================
# ⑤ 特定データセット明細
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
    if filter_col and filter_val:
        stmt = stmt.where(ExpenseRow.row_data[filter_col].astext.ilike(f"%{filter_val}%"))

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
        "data": [r.row_data for r in rows],
    }


# =====================================================
# ⑥ デバッグ用API
# =====================================================
@router.get("/_debug/dbinfo")
def debug_info(
    db: Session = Depends(get_db),
    user: str = Depends(basic_auth),
):
    total = db.scalar(select(func.count(ExpenseDataset.id)))
    by_branch = db.execute(
        select(ExpenseDataset.branch_name, func.count())
        .group_by(ExpenseDataset.branch_name)
    ).all()
    return {
        "database": "expenses",
        "datasets": total,
        "by_branch": {b or "未設定": c for b, c in by_branch},
    }
