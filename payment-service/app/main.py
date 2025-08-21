import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import create_database, test_connection, get_db
from redis_client import redis_client
from services.payment_service import payment_service
from routers import payment

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Variable global para el task del listener
listener_task = None

async def event_handler(event_data: dict):
    """Manejador de eventos PlanSelected"""
    try:
        if event_data.get("event_type") == "PlanSelected":
            # Obtener sesión de base de datos
            db = next(get_db())
            try:
                await payment_service.handle_plan_selected_event(db, event_data)
            finally:
                db.close()
    except Exception as e:
        logger.error(f"Error en event_handler: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestión del ciclo de vida de la aplicación"""
    global listener_task
    
    # Startup
    logger.info("Iniciando Payment Service...")
    
    # Configurar base de datos
    logger.info("Configurando base de datos...")
    create_database()
    if not test_connection():
        logger.error("No se pudo conectar a la base de datos")
        raise Exception("Error de conexión a la base de datos")
    
    # Conectar a Redis
    logger.info("Conectando a Redis...")
    if not await redis_client.connect():
        logger.error("No se pudo conectar a Redis")
        raise Exception("Error de conexión a Redis")
    
    # Iniciar listener de eventos
    logger.info("Iniciando listener de eventos...")
    listener_task = asyncio.create_task(redis_client.listen_for_events(event_handler))
    
    logger.info("Payment Service iniciado exitosamente")
    
    yield
    
    # Shutdown
    logger.info("Cerrando Payment Service...")
    
    # Detener listener
    if listener_task:
        await redis_client.stop_listening()
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass
    
    # Cerrar Redis
    await redis_client.close()
    logger.info("Payment Service cerrado")

# Crear aplicación FastAPI
app = FastAPI(
    title="FitFlow Payment Service",
    description="Microservicio de pagos para la plataforma FitFlow",
    version="1.0.0",
    lifespan=lifespan
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, especificar dominios específicos
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluir routers
app.include_router(payments.router, prefix="/api/v1", tags=["payments"])

@app.get("/")
async def root():
    """Endpoint raíz"""
    return {
        "service": "FitFlow Payment Service",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health():
    """Endpoint de salud completo"""
    # Verificar conexión a base de datos
    db_status = test_connection()
    
    # Verificar conexión a Redis
    redis_status = True
    try:
        await redis_client.client.ping()
    except:
        redis_status = False
    
    return {
        "service": "payment-service",
        "status": "healthy" if db_status and redis_status else "unhealthy",
        "database": "connected" if db_status else "disconnected",
        "redis": "connected" if redis_status else "disconnected",
        "version": "1.0.0"
    }

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("SERVICE_PORT", 8002))
    host = os.getenv("SERVICE_HOST", "0.0.0.0")
    
    logger.info(f"Iniciando servidor en {host}:{port}")
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )