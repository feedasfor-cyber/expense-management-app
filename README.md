# 小口現金管理ミニWebアプリ（FastAPI + SQLite/PostgreSQL）

CSVを**アップロード → 表表示（ページネーション／簡易検索） → 再ダウンロード**できる最小構成の業務向けWebアプリです。
提出要件を満たしつつ、実務を意識した**バリデーション／ログ／認証**なども実装しています。

---

## ✅ 課題要件に対する適合状況（チェックリスト）

### 機能要件
- **CSVアップロード（10MB上限、1行目ヘッダ）**
  - POST /api/expenses/ にて実装。拡張子 .csv、サイズ上限 10MB をチェック。UTF-8/UTF-8-SIG 対応。
  - 重複ヘッダ・列数不一致は 400 エラーで明示。
  - アップロード原本は uploads/ にタイムスタンプ付きファイル名で保存（再現性確保）。
- **アップロード一覧（名称／件数／日時）**
  - GET /api/expenses（クエリ：branch, period）で取得。
  - フロントは Bootstrap テーブル＋ページネーション表示。
- **詳細画面：表表示（ページネーション、単一列フィルタ）**
  - GET /api/expenses/{dataset_id}（クエリ：page,size,filter_val）で実装。
  - UIはモーダル表示でページ送り／件数切替に対応。
- **元CSVの再ダウンロード**
  - 条件で横断的に抽出 → GET /api/expenses/download_all_csv
  - 特定データセット単位 → GET /api/expenses/dataset_csv/{dataset_id}
- **永続化：RDS（任意エンジン）にメタ＋行データ保存**
  - 提出用は SQLite、本番想定は PostgreSQL（DATABASE_URLで切替）。
  - メタ情報＋行データ（JSONテキスト）を保存。
- **簡易認証（単一ユーザー想定）**
  - Basic 認証をミドルウェアで全リクエストに適用。
  - 既定ユーザー：admin／secret123（app/auth.py 参照）。

### 非機能要件
- エラーハンドリング（400／413／500）
- バリデーション（拡張子／サイズ／重複ヘッダ／列数不一致）
- ログ出力
- README にセットアップ・運用手順を記載

---

## 🧰 技術スタック
- Backend：FastAPI, SQLAlchemy
- DB：SQLite（提出）／PostgreSQL（本番想定）
- Frontend：HTML + Bootstrap 5 + Vanilla JS
- Auth：Basic 認証
- その他：CORS設定、例外ハンドラ、ストリーミングCSVレスポンス

---

## 📂 ディレクトリ構成（抜粋）

```
expense-app/
├── main.py
├── app/
│   ├── auth.py
│   ├── db.py
│   ├── logger.py
│   ├── models.py
│   ├── routers/
│   │   └── expenses.py
│   └── utils/
│       └── csv_validator.py
├── frontend/
│   └── index.html
├── uploads/
└── .env.example
```

---

## 🚀 ローカル導入・動作確認手順

### 0) 事前準備
- Python 3.10+

### 1) ソース取得＆仮想環境
```
# リポジトリ取得
git clone https://github.com/feedasfor-cyber/expense-management-app.git
cd expense-app

# 提出用ブランチに切り替え
git checkout submission-sqlite

# 仮想環境の作成と有効化（Windows）
python -m venv venv
.\venv\Scripts\activate

# macOS / Linux
# python3 -m venv venv
# source venv/bin/activate
```

### 2) 依存パッケージのインストール
```
pip install fastapi "uvicorn[standard]" sqlalchemy python-multipart
# PostgreSQLを使う場合
# pip install psycopg2-binary
```

### 3) DB設定
```
このプロジェクトでは、環境変数の雛形として.env.exampleファイルを用意しています。
このファイルをコピーして.envにリネームすることで、すぐに実行できるようになります。

# Windows の場合（PowerShell）
copy .env.example .env

expense-management-app\
│
├── .env               ← ここに置く！
├── main.py
├── app/
├── frontend/
└── ...
うまくいけば、uvicorn で起動したときに自動的に app.db が生成されます。
```

### 4) アプリ起動
```
uvicorn main:app --reload
```

### 5) 初回アクセスと認証
- http://127.0.0.1:8000 にアクセス
- Basic認証：admin / secret123
- 認証後、自動的に frontend/index.html（UI）が表示されます


### 6) UIで動作確認

画面上部の「小口現金CSVアップロード」で

- 支店名：例）大阪支店
- 対象月：例）2025-10
- CSVファイル：以下のようなヘッダを推奨（順不同でも可）
```
金額,勘定科目,備考
1200,交通費,地下鉄
800,会議費,コーヒー
```

「アップロード」→ 下部「アップロード履歴」に追加されます
履歴の「詳細」でモーダルが開き、ページ送り／件数切替できます
履歴の「DL」で条件（支店／対象月）一致のCSVを一括ダウンロード
中段「検索してプレビュー／CSVダウンロード」では、勘定科目等で絞込 → 画面プレビュー／CSV保存

### 7) APIテスト例
```
curl -u admin:secret123 "http://127.0.0.1:8000/api/expenses"
```

---

## 🔐 認証仕様
- Basic認証
- デフォルト：admin / secret123
- app/auth.py で変更可能

---

## 📚 API一覧

| メソッド | パス | 概要 |
|----------|------|------|
| POST | /api/expenses/ | CSVアップロード |
| GET | /api/expenses | 履歴取得 |
| GET | /api/expenses/download_all_json | プレビュー |
| GET | /api/expenses/download_all_csv | 横断CSV |
| GET | /api/expenses/dataset_csv/{id} | 特定CSV |
| GET | /api/expenses/{id} | 明細取得 |

---

## ログ／再現性

- アップロード原本は uploads/ 配下にタイムスタンプ付きで保存（例：20251012_153012_sample.csv）
- INFO ログ：ユーザー名／支店名／対象月／行数などを記録（app.log ほか logs/app.log）
- 例外はグローバルハンドラで整形して返却（main.py）

## ✨ 追加実装（PR 形式）

- PR #1: 横断プレビュー & CSVダウンロード機能
- PR #2: 末尾スラッシュ互換対応
- PR #3: アップロード原本の保存とメタ管理
- PR #4: グローバル例外ハンドラ & バリデーション強化
- PR #5: UI/UX改善（詳細モーダル・ページング・即時DL）

---

## ⚠️ 注意点
- 数値・日付の厳密な検索はUI側のみ対応
- Basic認証情報は簡易化用（本番は環境変数推奨）
- PostgreSQL対応済（env切替）