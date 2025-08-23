from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func
from db import Base

class Notification(Base):
    __tablename__ = "notificaciones"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(128), nullable=True)
    notification_type = Column(String(32), nullable=False)  
    service = Column(String(64), nullable=False)  
    medio = Column(String(32), default="email")
    status = Column(String(32), default="SENT")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
