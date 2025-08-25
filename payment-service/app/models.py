from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.sql import func
from database import Base
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

# SQLAlchemy Models
class Payment(Base):
    __tablename__ = "payments"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    plan_id = Column(Integer, nullable=False)
    plan_name = Column(String(100), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="USD")
    status = Column(String(20), default="pending")  # pending, completed, failed
    payment_method = Column(String(50), default="credit_card")
    transaction_id = Column(String(100), unique=True, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    processed_at = Column(DateTime, nullable=True)

# Pydantic Models (Request/Response)
class PaymentRequest(BaseModel):
    plan_id: int
    payment_method: str = "credit_card"
    card_number: Optional[str] = None
    card_holder: Optional[str] = None
    expiry_date: Optional[str] = None
    cvv: Optional[str] = None

class PaymentResponse(BaseModel):
    id: int
    user_id: int
    plan_id: int
    plan_name: str
    amount: float
    currency: str
    status: str
    payment_method: str
    transaction_id: Optional[str]
    created_at: datetime
    processed_at: Optional[datetime]
    
    class Config:
        from_attributes = True

class PaymentStatus(BaseModel):
    payment_id: int
    status: str
    transaction_id: Optional[str]
    processed_at: Optional[datetime]

# Event Models
class PlanSelectedEvent(BaseModel):
    event_type: str = "PlanSelected"
    user_id: int
    plan_id: int
    plan_name: str
    plan_price: float
    timestamp: datetime

class PaymentProcessedEvent(BaseModel):
    event_type: str = "PaymentProcessed"
    payment_id: int
    user_id: int
    plan_id: int
    plan_name: str
    amount: float
    status: str
    transaction_id: Optional[str]
    timestamp: datetime

# Plan information (esto vendría del User Service en un escenario real)
PLANS_INFO = {
    1: {"name": "Plan Básico", "price": 29.99},
    2: {"name": "Plan Estándar", "price": 49.99},
    3: {"name": "Plan Premium", "price": 79.99}
}   