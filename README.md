# Expense Management App
## API 仕様（最小構成）

### POST /api/expenses
- 内容: CSVアップロード（multipart/form-data, フィールド名: `file`）
- バリデーション:
  - 拡張子: `.csv` のみ
  - サイズ: 10MB 以下
  - 1行目: ヘッダ必須 / 重複不可
  - 列数: 各行で一致
  - 金額列が数値、日付列が有効日付（任意で強化）
- レスポンス例:
```json
{ "dataset_id": 1, "row_count": 120, "warnings": 0 }