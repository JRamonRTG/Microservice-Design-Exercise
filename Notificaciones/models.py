from typing import List
from pydantic import BaseModel

class Notification(BaseModel):
    user_id: int
    message: str
