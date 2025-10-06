# app/models.py
CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS expense_datasets (
    id SERIAL PRIMARY KEY,
    file_name TEXT NOT NULL,
    row_count INT NOT NULL,
    uploaded_at TIMESTAMP DEFAULT NOW(),
    uploader TEXT,
    original_path TEXT
);

CREATE TABLE IF NOT EXISTS expense_rows (
    id SERIAL PRIMARY KEY,
    dataset_id INT NOT NULL REFERENCES expense_datasets(id) ON DELETE CASCADE,
    row_data JSONB NOT NULL
);

-- よく使う列に対してJSONBのPathOpsで検索を速くしたい場合の例（任意）
-- CREATE INDEX IF NOT EXISTS idx_expense_rows_row_data ON expense_rows USING GIN (row_data);
"""
