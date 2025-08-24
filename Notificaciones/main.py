from fastapi import FastAPI
from typing import List
import httpx
import asyncio
from models import Notification
from schemas import NotificationSchema

app = FastAPI(title="Notification Service")

notifications: List[Notification] = []

USER_SERVICE_URL = "https://user-service.mangorock-bc5d8fa9.eastus.azurecontainerapps.io"

async def fetch_new_users():
    async with httpx.AsyncClient() as client:
        while True:
            try:
                response = await client.get(f"{USER_SERVICE_URL}/users")
                if response.status_code == 200:
                    users = response.json()
                    for user in users:
                        # Verificar si ya existe la notificación
                        if not any(n.user_id == user["id"] for n in notifications):
                            notifications.append(Notification(
                                user_id=user["id"],
                                message=f"Usuario {user['name']} registrado con email {user['email']}"
                            ))
            except Exception as e:
                print(f"Error conectando con User Service: {e}")
            await asyncio.sleep(5)  

@app.get("/notifications", response_model=List[NotificationSchema])
async def get_notifications():
    return notifications

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(fetch_new_users())
