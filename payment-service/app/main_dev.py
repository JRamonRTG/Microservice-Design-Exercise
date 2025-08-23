import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional
from datetime import datetime

# Añadir el directorio actual al path
sys.path.append(str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Crear aplicación FastAPI
app = FastAPI(
    title="FitFlow Payment Service - DEV",
    description="Microservicio de pagos para la plataforma FitFlow (Versión desarrollo)",
    version="1.0.0-dev"
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== MODELOS SIMPLES PARA DESARROLLO =====
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

class PaymentStatus(BaseModel):
    payment_id: int
    status: str
    transaction_id: Optional[str]
    processed_at: Optional[datetime]

# Información de planes
PLANS_INFO = {
    1: {"name": "Plan Básico", "price": 29.99},
    2: {"name": "Plan Estándar", "price": 49.99},
    3: {"name": "Plan Premium", "price": 79.99}
}

# Almacenamiento en memoria para desarrollo
payments_store = {}
payment_counter = 1

# ===== ENDPOINTS =====
@app.get("/")
async def root():
    """Endpoint raíz"""
    return {
        "service": "FitFlow Payment Service - DEV",
        "version": "1.0.0-dev",
        "status": "running",
        "note": "Versión de desarrollo - datos en memoria"
    }

@app.get("/health")
async def health():
    """Endpoint de salud básico"""
    # Verificar Redis si está disponible
    redis_status = True
    try:
        from redis_client import redis_client
        await redis_client.client.ping()
    except Exception as e:
        redis_status = False
        logger.warning(f"Redis no disponible: {e}")
    
    return {
        "service": "payment-service-dev",
        "status": "healthy",
        "redis": "connected" if redis_status else "disconnected",
        "database": "memory",
        "version": "1.0.0-dev"
    }

@app.get("/api/v1/health")
async def health_check():
    """Endpoint de salud del servicio"""
    return {"status": "healthy", "service": "payment-service-dev"}

@app.get("/api/v1/plans")
async def get_available_plans():
    """Obtener planes disponibles"""
    return {"plans": PLANS_INFO}

@app.post("/api/v1/payments/{user_id}", response_model=PaymentResponse)
async def create_payment(
    user_id: int,
    payment_request: PaymentRequest
):
    """Crear un nuevo pago para un usuario"""
    global payment_counter
    
    try:
        # Validar que el usuario existe
        if user_id <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ID de usuario inválido"
            )
        
        # Validar que el plan existe
        if payment_request.plan_id not in PLANS_INFO:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Plan {payment_request.plan_id} no encontrado"
            )
        
        plan_info = PLANS_INFO[payment_request.plan_id]
        
        # Crear el pago
        payment = PaymentResponse(
            id=payment_counter,
            user_id=user_id,
            plan_id=payment_request.plan_id,
            plan_name=plan_info["name"],
            amount=plan_info["price"],
            currency="USD",
            status="pending",
            payment_method=payment_request.payment_method,
            transaction_id=None,
            created_at=datetime.utcnow()
        )
        
        # Guardar en memoria
        payments_store[payment_counter] = payment
        payment_counter += 1
        
        logger.info(f"Pago creado: ID {payment.id} para usuario {user_id}")
        return payment
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )

@app.post("/api/v1/payments/{payment_id}/process", response_model=PaymentStatus)
async def process_payment(payment_id: int):
    """Procesar un pago pendiente"""
    try:
        if payment_id not in payments_store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pago {payment_id} no encontrado"
            )
        
        payment = payments_store[payment_id]
        
        if payment.status != "pending":
            raise ValueError(f"El pago {payment_id} ya fue procesado")
        
        # Simular procesamiento
        import random
        import uuid
        success = random.random() < 0.95  # 95% de éxito
        
        if success:
            payment.status = "completed"
            payment.transaction_id = str(uuid.uuid4())
            processed_at = datetime.utcnow()
            logger.info(f"Pago {payment_id} procesado exitosamente")
        else:
            payment.status = "failed"
            processed_at = datetime.utcnow()
            logger.warning(f"Pago {payment_id} falló")
        
        # Actualizar en memoria
        payments_store[payment_id] = payment
        
        return PaymentStatus(
            payment_id=payment.id,
            status=payment.status,
            transaction_id=payment.transaction_id,
            processed_at=processed_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )

@app.get("/api/v1/payments/{payment_id}", response_model=PaymentResponse)
async def get_payment(payment_id: int):
    """Obtener información de un pago específico"""
    if payment_id not in payments_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pago {payment_id} no encontrado"
        )
    
    return payments_store[payment_id]

@app.get("/api/v1/users/{user_id}/payments", response_model=List[PaymentResponse])
async def get_user_payments(
    user_id: int,
    skip: int = 0,
    limit: int = 10
):
    """Obtener todos los pagos de un usuario"""
    if user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de usuario inválido"
        )
    
    user_payments = [p for p in payments_store.values() if p.user_id == user_id]
    return user_payments[skip:skip + limit]

@app.get("/api/v1/payments", response_model=List[PaymentResponse])
async def get_all_payments(skip: int = 0, limit: int = 100):
    """Obtener todos los pagos (para admin/debug)"""
    all_payments = list(payments_store.values())
    return all_payments[skip:skip + limit]

# Endpoint especial para limpiar datos de desarrollo
@app.delete("/api/v1/dev/clear")
async def clear_dev_data():
    """Limpiar datos de desarrollo"""
    global payments_store, payment_counter
    payments_store.clear()
    payment_counter = 1
    return {"message": "Datos de desarrollo limpiados"}

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("SERVICE_PORT", 8002))
    host = os.getenv("SERVICE_HOST", "0.0.0.0")
    
    logger.info(f"Iniciando Payment Service DEV en {host}:{port}")
    logger.info("Usando almacenamiento en memoria")
    logger.info("Endpoints disponibles:")
    logger.info("   - http://localhost:8002/")
    logger.info("   - http://localhost:8002/health")
    logger.info("   - http://localhost:8002/api/v1/plans")
    logger.info("   - http://localhost:8002/docs (Swagger UI)")
    
    uvicorn.run(
        "main_dev:app",
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )