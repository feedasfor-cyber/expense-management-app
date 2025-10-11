# app/models.py
# from sqlalchemy import (
#     Column, Integer, Text, TIMESTAMP, ForeignKey, func, Index
# )
# from sqlalchemy.dialects.postgresql import JSONB
# from sqlalchemy.orm import relationship
# from .db import Base

# アップロードされたCSVのメタ情報
# class ExpenseDataset(Base):
#     __tablename__ = "expense_datasets"

#     id = Column(Integer, primary_key=True, index=True)
#     file_name = Column(Text, nullable=False)
#     row_count = Column(Integer, nullable=False)
#     uploader = Column(Text)
#     original_path = Column(Text, nullable=False)
#     uploaded_at = Column(TIMESTAMP, nullable=False, server_default=func.now())
#     branch_name = Column(Text)  # 例：大阪支店
#     period = Column(Text)       # 例：2025-10

#     rows = relationship("ExpenseRow", back_populates="dataset", cascade="all, delete-orphan")

#     __table_args__ = (
#         Index("idx_expense_datasets_period", "period"),
#         Index("idx_expense_datasets_branch", "branch_name"),
#     )

# 各CSVの行データ（JSON形式で保存）
# class ExpenseRow(Base):
#     __tablename__ = "expense_rows"

#     id = Column(Integer, primary_key=True, index=True)
#     dataset_id = Column(Integer, ForeignKey("expense_datasets.id", ondelete="CASCADE"), nullable=False)
#     row_data = Column(JSONB, nullable=False)

#     dataset = relationship("ExpenseDataset", back_populates="rows")

#     __table_args__ = (
#         Index("idx_expense_rows_dataset", "dataset_id"),
#         Index("idx_expense_rows_rowdata", "row_data", postgresql_using="gin"),
#     )

from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, func, Index
from sqlalchemy.orm import relationship
from datetime import datetime
import json

from app.db import Base

class ExpenseDataset(Base):
    __tablename__ = "expense_datasets"

    id = Column(Integer, primary_key=True, index=True)
    file_name = Column(String, nullable=False)
    row_count = Column(Integer, nullable=False)
    uploader = Column(String, nullable=True)
    original_path = Column(String, nullable=True)
    branch_name = Column(String, nullable=True)
    period = Column(String, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    rows = relationship("ExpenseRow", back_populates="dataset", cascade="all, delete-orphan")


class ExpenseRow(Base):
    __tablename__ = "expense_rows"

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("expense_datasets.id", ondelete="CASCADE"), nullable=False)
    row_data = Column(Text, nullable=False)  # ← JSONBではなくTextでOK

    dataset = relationship("ExpenseDataset", back_populates="rows")

    __table_args__ = (
        Index("idx_expense_rows_dataset", "dataset_id"),
    )

    def as_dict(self):
        return json.loads(self.row_data)
