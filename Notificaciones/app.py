import json
from fastapi import FastAPI, Request, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import inspect
from db import Base, engine, SessionLocal
from models import Notification

app = FastAPI()

inspector = inspect(engine)
if not inspector.has_table("notificaciones"):
    Base.metadata.create_all(bind=engine)

def guardar_notificacion(notification_type: str, datos: dict):
    db: Session = SessionLocal()
    try:
        notif = Notification(
            user_id=str(datos.get("user_id")) if datos.get("user_id") else None,
            notification_type=notification_type,
            service=datos.get("service"),
            medio=datos.get("medio", "email"),
            status=datos.get("status", "SENT")
        )
        db.add(notif)
        db.commit()
        db.refresh(notif)
        return notif
    finally:
        db.close()

@app.post("/events")
async def receive_event(request: Request):
    body = await request.json()
    notification_type = body.get("notification_type")
    datos = body.get("datos")
    if not notification_type or not datos:
        raise HTTPException(status_code=400, detail="Invalid event format. Expected {notification_type, datos}")
    notif = guardar_notificacion(notification_type, datos)
    return {"id": notif.id, "notification_type": notif.notification_type, "status": notif.status}

@app.get("/obtener_notificaciones")
def list_notifications():
    db: Session = SessionLocal()
    try:
        rows = db.query(Notification).order_by(Notification.created_at.desc()).all()
        return [
            {
                "id": r.id,
                "user_id": r.user_id,
                "notification_type": r.notification_type,
                "service": r.service,
                "medio": r.medio,
                "status": r.status,
                "created_at": r.created_at.isoformat()
            }
            for r in rows
        ]
    finally:
        db.close()

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/notificacion_por_usuario/{user_id}")
def get_notification_by_user(user_id: str):
    db: Session = SessionLocal()
    try:
        notif = db.query(Notification).filter(Notification.user_id == user_id).order_by(Notification.created_at.desc()).first()
        if not notif:
            raise HTTPException(status_code=404, detail="Notificación no encontrada para ese usuario")
        return {
            "id": notif.id,
            "user_id": notif.user_id,
            "notification_type": notif.notification_type,
            "service": notif.service,
            "medio": notif.medio,
            "status": notif.status,
            "created_at": notif.created_at.isoformat()
        }
    finally:
        db.close()

@app.get("/notificacion/{notificacion_id}")
def get_notification_by_id(notificacion_id: int):
    db: Session = SessionLocal()
    try:
        notif = db.query(Notification).filter(Notification.id == notificacion_id).first()
        if not notif:
            raise HTTPException(status_code=404, detail="Notificación no encontrada")
        return {
            "id": notif.id,
            "user_id": notif.user_id,
            "notification_type": notif.notification_type,
            "service": notif.service,
            "medio": notif.medio,
            "status": notif.status,
            "created_at": notif.created_at.isoformat()
        }
    finally:
        db.close()

@app.delete("/notificacion/{notificacion_id}")
def delete_notification(notificacion_id: int):
    db: Session = SessionLocal()
    try:
        notif = db.query(Notification).filter(Notification.id == notificacion_id).first()
        if not notif:
            raise HTTPException(status_code=404, detail="Notificación no encontrada")
        db.delete(notif)
        db.commit()
        return {"detail": "Notificación eliminada"}
    finally:
        db.close()

@app.put("/notificacion/{notificacion_id}/status")
def update_notification_status(notificacion_id: int, status: str):
    db: Session = SessionLocal()
    try:
        notif = db.query(Notification).filter(Notification.id == notificacion_id).first()
        if not notif:
            raise HTTPException(status_code=404, detail="Notificación no encontrada")
        notif.status = status
        db.commit()
        db.refresh(notif)
        return {"id": notif.id, "status": notif.status}
    finally:
        db.close()
