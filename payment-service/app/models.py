
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Literal
from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from pydantic import BaseModel
from .database import Base

PLANS_INFO: Dict[int, Dict[str, Any]] = {
    1: {"name": "Plan Básico", "price": 19.99},
    2: {"name": "Plan Estándar", "price": 49.99},
    3: {"name": "Plan Premium", "price": 79.99}
}

# SQLAlchemy model
class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    plan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_name: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    transaction_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

# Pydantic models
PaymentStatus = Literal["pending", "completed"]

class PaymentRequest(BaseModel):
    plan_id: int

class PaymentResponse(BaseModel):
    id: int
    user_id: int
    plan_id: int
    plan_name: str
    amount: float
    status: str
    transaction_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class PaymentProcessedEvent(BaseModel):
    payment_id: int
    user_id: int
    status: str
    amount: float
    transaction_id: str
    timestamp: datetime
