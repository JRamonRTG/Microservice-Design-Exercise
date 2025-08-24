import os
import json
import asyncio
import redis.asyncio as redis
from typing import Dict, Any, Callable
from dotenv import load_dotenv
import logging

load_dotenv()

logger = logging.getLogger(__name__)

class RedisEventClient:
    def __init__(self):
        self.redis_host = os.getenv("REDIS_HOST", "localhost")
        self.redis_port = int(os.getenv("REDIS_PORT", 6379))
        self.redis_password = os.getenv("REDIS_PASSWORD", "")
        
        # Azure Redis connection string
        azure_redis_connection = os.getenv("AZURE_REDIS_CONNECTION_STRING")
        
        if azure_redis_connection:
            self.client = redis.from_url(azure_redis_connection)
        else:
            self.client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                password=self.redis_password if self.redis_password else None,
                decode_responses=True
            )
        
        self.consumer_group = "payment-service-group"
        self.consumer_name = "payment-consumer"
        self.running = False
    
    async def connect(self):
        """Conectar y configurar Redis Streams"""
        try:
            await self.client.ping()
            logger.info("Conectado a Redis exitosamente")
            
            # Crear consumer group para PlanSelected events
            try:
                await self.client.xgroup_create("fitflow:events:PlanSelected", self.consumer_group, id="0", mkstream=True)
                logger.info(f"Consumer group '{self.consumer_group}' creado para PlanSelected")
            except RedisError as e:
                if "BUSYGROUP" in str(e):
                    logger.info(f"Consumer group '{self.consumer_group}' ya existe")
                else:
                    raise e
            
            return True
        except Exception as e:
            logger.error(f"Error conectando a Redis: {e}")
            return False
    
    async def publish_event(self, stream_key: str, event_data: Dict[str, Any]):
        """Publicar evento en Redis Stream"""
        try:
            # Convertir todos los valores a string para Redis
            redis_data = {}
            for key, value in event_data.items():
                if isinstance(value, (dict, list)):
                    redis_data[key] = json.dumps(value)
                else:
                    redis_data[key] = str(value)
            
            message_id = await self.client.xadd(stream_key, redis_data)
            logger.info(f"Evento publicado en {stream_key}: {message_id}")
            return message_id
        except Exception as e:
            logger.error(f"Error publicando evento: {e}")
            raise
    
    async def listen_for_events(self, event_handler: Callable):
        """Escuchar eventos de PlanSelected"""
        self.running = True
        logger.info("Iniciando listener de eventos PlanSelected...")
        
        while self.running:
            try:
                # Leer mensajes del stream
                messages = await self.client.xreadgroup(
                    self.consumer_group,
                    self.consumer_name,
                    {"fitflow:events:PlanSelected": ">"},
                    count=1,
                    block=1000
                )
                
                for stream, msgs in messages:
                    for msg_id, fields in msgs:
                        try:
                            # Procesar el evento
                            event_data = {}
                            for key, value in fields.items():
                                try:
                                    # Intentar parsear como JSON
                                    event_data[key] = json.loads(value)
                                except:
                                    # Si no es JSON, mantener como string
                                    event_data[key] = value
                            
                            logger.info(f"Procesando evento: {msg_id}")
                            await event_handler(event_data)
                            
                            # Confirmar procesamiento
                            await self.client.xack("fitflow:events:PlanSelected", self.consumer_group, msg_id)
                            
                        except Exception as e:
                            logger.error(f"Error procesando mensaje {msg_id}: {e}")
                            
            except Exception as e:
                logger.error(f"Error en listener de eventos: {e}")
                await asyncio.sleep(5)  # Esperar antes de reintentar
    
    async def publish_payment_processed(self, payment_data: Dict[str, Any]):
        """Publicar evento PaymentProcessed"""
        stream_key = "fitflow:events:PaymentProcessed"
        await self.publish_event(stream_key, payment_data)
    
    async def stop_listening(self):
        """Detener el listener de eventos"""
        self.running = False
        logger.info("Deteniendo listener de eventos...")
    
    async def close(self):
        """Cerrar conexión Redis"""
        await self.client.close()
        logger.info("Conexión Redis cerrada")

# Instancia global del cliente Redis
redis_client = RedisEventClient()