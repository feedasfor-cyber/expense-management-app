import csv
import io
from fastapi import HTTPException, UploadFile

def validate_csv(file: UploadFile):
    """
    CSVの基本バリデーション：
    - 拡張子 .csv
    - サイズ 10MB 以下
    - 空ファイルNG
    - ヘッダ重複なし
    - 各行の列数一致
    """

    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="CSVファイルのみ対応しています。")

    # ファイル内容を読み込み
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty CSV file.")

    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="10MBを超えるファイルはアップロードできません。")

    # デコードしてCSVパース
    try:
        text = content.decode("utf-8-sig")  # BOM付きUTF-8も対応
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"CSV解析エラー: {str(e)}")

    if len(rows) < 2:
        raise HTTPException(status_code=400, detail="CSVにデータ行がありません。")

    headers = rows[0]
    if len(headers) != len(set(headers)):
        raise HTTPException(status_code=400, detail="重複したヘッダがあります。")

    # 各行の列数をチェック
    for i, row in enumerate(rows[1:], start=2):
        if len(row) != len(headers):
            raise HTTPException(status_code=400, detail=f"{i}行目で列数が一致しません。")

    # 戻り値: headersとデータ行（2行目以降）
    return headers, rows[1:]
