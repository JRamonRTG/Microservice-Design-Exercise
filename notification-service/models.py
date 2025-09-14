
from pydantic import BaseModel
from datetime import datetime

class Notification(BaseModel):
    id: int
    user_id: int
    message: str
    created_at: datetime
    correlation_id: str | None = None
