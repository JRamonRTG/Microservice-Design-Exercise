import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
import pytds

# Cargar variables de entorno (útil en local)
load_dotenv()

# Crear la aplicación FastAPI
app = FastAPI(title="User Service", version="1.0")

# ----------- Configuración de DB -----------
DB_SERVER = os.getenv("DB_SERVER")       # ej: services2025.database.windows.net
DB_NAME = os.getenv("DB_NAME")           # ej: services
DB_USER = os.getenv("DB_USER")           # ej: user
DB_PASSWORD = os.getenv("DB_PASSWORD")   # ej: Prueba2025-

def get_connection():
    return pytds.connect(
        server=DB_SERVER,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        port=1433,
        encryption=True,
        trust_server_certificate=False
    )

# ----------- Modelos de entrada -----------
class UserRegister(BaseModel):
    name: str
    email: str

class PlanSelection(BaseModel):
    plan_name: str

# ----------- Endpoints -------------------
@app.get("/")
def root():
    return {
        "service": "User Service",
        "status": "ok",
        "docs": "/docs"
    }

@app.post("/users/register")
def register_user(user: UserRegister):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO Users (name, email) VALUES (%s, %s)", (user.name, user.email))
        conn.commit()
        conn.close()
        return {"message": f"Usuario {user.name} registrado con éxito."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/users/{user_id}/select-plan")
def select_plan(user_id: int, plan: PlanSelection):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE Users SET plan = %s WHERE id = %s", (plan.plan_name, user_id))
        conn.commit()
        conn.close()
        return {"message": f"Usuario {user_id} actualizado al plan {plan.plan_name}."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))