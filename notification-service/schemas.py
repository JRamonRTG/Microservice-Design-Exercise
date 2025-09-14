
from pydantic import BaseModel

class NotificationSchema(BaseModel):
    user_id: int
    message: str
