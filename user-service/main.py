from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pyodbc
import os

app = FastAPI()

# Modelos para las solicitudes
class UserRegister(BaseModel):
    name: str
    email: str

class PlanSelection(BaseModel):
    plan_name: str

# Obtener cadena de conexión desde variables de entorno
def get_connection():
    conn_str = os.getenv("DATABASE_URL")
    if not conn_str:
        raise Exception("DATABASE_URL no está definida en variables de entorno")
    return pyodbc.connect(conn_str)

# Endpoint raíz para pruebas
@app.get("/")
def root():
    return {"message": "Microservicio de usuarios activo"}

# Registro de usuario
@app.post("/users/register")
def register_user(user: UserRegister):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            user.name, user.email
        )
        conn.commit()
        return {"message": "Usuario registrado con éxito"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

# Selección de plan
@app.post("/users/{user_id}/select-plan")
def select_plan(user_id: int, plan: PlanSelection):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "UPDATE users SET plan = ? WHERE id = ?",
            plan.plan_name, user_id
        )
        conn.commit()
        return {"message": f"Plan '{plan.plan_name}' asignado al usuario {user_id}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()
