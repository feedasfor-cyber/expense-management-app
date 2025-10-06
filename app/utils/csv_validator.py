import csv
import io
from fastapi import HTTPException, UploadFile

def validate_csv(file):
    """
    CSVファイルのヘッダ・行データを検証して返す（UploadFile / BytesIO 両対応）

    検証内容：
    - 拡張子が .csv（UploadFile時のみ）
    - 空ファイルでない
    - UTF-8 / UTF-8-SIG に対応
    - ヘッダ重複なし
    - 各行の列数一致
    """

    # --- 🧩 どちらの形式（UploadFile or BytesIO）かを判定 ---
    if hasattr(file, "file"):  # UploadFile型
        filename = file.filename
        raw_bytes = file.file.read()
    elif isinstance(file, io.BytesIO):  # BytesIO型（rawから擬似ファイルを作ったケース）
        filename = "uploaded_memory.csv"
        raw_bytes = file.getvalue()
    else:
        raise HTTPException(status_code=400, detail="無効なファイル型です。")

    # --- 基本チェック ---
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="空のCSVです。")
    if hasattr(file, "filename") and not filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="CSVファイルのみ対応しています。")

    # --- CSVとしてパース ---
    try:
        text = raw_bytes.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"CSV解析エラー: {e}")

    if len(rows) < 2:
        raise HTTPException(status_code=400, detail="CSVにデータ行がありません。")

    headers = rows[0]
    data_rows = rows[1:]

    # --- 検証 ---
    if len(headers) != len(set(headers)):
        raise HTTPException(status_code=400, detail="重複したヘッダがあります。")

    for i, row in enumerate(data_rows, start=2):
        if len(row) != len(headers):
            raise HTTPException(status_code=400, detail=f"{i}行目で列数が一致しません。")

    return headers, data_rows
