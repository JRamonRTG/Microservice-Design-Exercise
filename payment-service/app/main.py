import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import create_database, test_connection, get_db, ensure_database_exists
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
database_available = False

async def event_handler(event_data: dict):
    """Manejador de eventos PlanSelected"""
    try:
        if event_data.get("event_type") == "PlanSelected" and database_available:
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
    global listener_task, database_available
    
    # Startup
    logger.info("Iniciando Payment Service...")
    
    # PASO 1: Asegurar que la base de datos existe
    logger.info("Verificando base de datos...")
    if ensure_database_exists():
        logger.info("Base de datos disponible")
        
        # PASO 2: Configurar tablas y esquema
        logger.info("Configurando esquema de base de datos...")
        create_database()
        
        # PASO 3: Probar conexión
        if test_connection():
            database_available = True
            logger.info("Base de datos conectada y lista")
        else:
            logger.warning("Problema con conexión de base de datos - continuando sin DB")
    else:
        logger.warning("No se pudo asegurar base de datos - continuando sin DB")
    
    # PASO 4: Conectar a Redis
    logger.info("🔧 Conectando a Redis...")
    redis_connected = await redis_client.connect()
    if redis_connected:
        logger.info("Redis conectado")
        
        # PASO 5: Iniciar listener de eventos solo si Redis funciona
        logger.info("🔧 Iniciando listener de eventos...")
        listener_task = asyncio.create_task(redis_client.listen_for_events(event_handler))
        logger.info("Listener de eventos iniciado")
    else:
        logger.warning("Redis no disponible - continuando sin eventos")
    
    # PASO 6: Resumen del estado
    if database_available and redis_connected:
        logger.info("Payment Service iniciado completamente")
    elif database_available:
        logger.info("Payment Service iniciado (sin Redis)")
    elif redis_connected:
        logger.info("Payment Service iniciado (sin base de datos)")
    else:
        logger.warning("Payment Service iniciado en modo limitado (sin DB ni Redis)")
    
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
    if redis_connected:
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
app.include_router(payment.router, prefix="/api/v1", tags=["payments"])

@app.get("/")
async def root():
    """Endpoint raíz"""
    return {
        "service": "FitFlow Payment Service",
        "version": "1.0.0",
        "status": "running",
        "database": "available" if database_available else "unavailable",
        "mode": "full" if database_available else "limited"
    }

@app.get("/health")
async def health():
    """Endpoint de salud completo"""
    # Verificar conexión a base de datos
    db_status = database_available and test_connection()
    
    # Verificar conexión a Redis
    redis_status = True
    try:
        await redis_client.client.ping()
    except:
        redis_status = False
    
    # Determinar estado general
    if db_status and redis_status:
        overall_status = "healthy"
    elif db_status or redis_status:
        overall_status = "degraded"
    else:
        overall_status = "limited"
    
    return {
        "service": "payment-service",
        "status": overall_status,
        "database": "connected" if db_status else "disconnected",
        "redis": "connected" if redis_status else "disconnected",
        "version": "1.0.0",
        "capabilities": {
            "payments": True,  # Siempre disponible (puede usar memoria)
            "persistence": db_status,
            "events": redis_status
        }
    }

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("SERVICE_PORT", 8002))
    host = os.getenv("SERVICE_HOST", "0.0.0.0")
    
    logger.info(f"Iniciando servidor en {host}:{port}")
    logger.info("Documentación disponible en: http://localhost:8002/docs")
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )