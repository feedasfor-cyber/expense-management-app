# seed_test_data.py
from app.db import SessionLocal
from app.models import ExpenseDataset, ExpenseRow
from datetime import datetime, timedelta
import random

# === 設定 ===
BRANCHES = ["東京支店", "大阪支店", "名古屋支店", "福岡支店"]
ACCOUNTS = ["旅費交通費", "会議費", "交際費", "消耗品費", "通信費"]
EMPLOYEES = ["山田太郎", "佐藤花子", "田中一郎", "高橋次郎", "鈴木美咲"]

# === セッション作成 ===
db = SessionLocal()

# === クリアしたい場合 ===
# db.query(ExpenseRow).delete()
# db.query(ExpenseDataset).delete()
# db.commit()

# === データ投入 ===
for i in range(100):
    branch = random.choice(BRANCHES)
    period = f"2025-{random.randint(1, 12):02d}"

    dataset = ExpenseDataset(
        file_name=f"dummy_{i+1}.csv",
        row_count=10,
        original_path=f"uploads/dummy_{i+1}.csv",
        branch_name=branch,
        period=period,
    )
    db.add(dataset)
    db.flush()  # dataset.idを取得するため

    # 各データセットに10行の明細を追加
    for j in range(10):
        employee = random.choice(EMPLOYEES)
        account = random.choice(ACCOUNTS)
        date = datetime(2025, random.randint(1, 12), random.randint(1, 28))
        amount = random.randint(1000, 50000)
        row = ExpenseRow(
            dataset_id=dataset.id,
            row_data={
                "日付": date.strftime("%Y-%m-%d"),
                "部署": f"{branch} 経理部",
                "社員名": employee,
                "金額": str(amount),
                "勘定科目": account,
                "備考": f"テストデータ{j+1}",
            },
        )
        db.add(row)

db.commit()
db.close()

print("✅ ダミーデータ100件（各10行）を登録しました！")
