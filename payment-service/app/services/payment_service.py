import uuid
import asyncio
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc

from models import Payment, PaymentRequest, PLANS_INFO, PaymentProcessedEvent
from redis_client import redis_client

logger = logging.getLogger(__name__)

class PaymentService:
    def __init__(self):
        pass
    
    def create_payment(self, db: Session, user_id: int, payment_request: PaymentRequest) -> Payment:
        """Crear un nuevo pago"""
        try:
            # Obtener información del plan
            plan_info = PLANS_INFO.get(payment_request.plan_id)
            if not plan_info:
                raise ValueError(f"Plan {payment_request.plan_id} no encontrado")
            
            # Crear el pago
            payment = Payment(
                user_id=user_id,
                plan_id=payment_request.plan_id,
                plan_name=plan_info["name"],
                amount=plan_info["price"],
                payment_method=payment_request.payment_method,
                status="pending"
            )
            
            db.add(payment)
            db.commit()
            db.refresh(payment)
            
            logger.info(f"Pago creado: ID {payment.id} para usuario {user_id}")
            return payment
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error creando pago: {e}")
            raise
    
    def process_payment(self, db: Session, payment_id: int) -> Optional[Payment]:
        """Procesar un pago (simulación)"""
        try:
            payment = db.query(Payment).filter(Payment.id == payment_id).first()
            if not payment:
                return None
            
            if payment.status != "pending":
                raise ValueError(f"El pago {payment_id} ya fue procesado")
            
            # Simular procesamiento de pago
            success = self._simulate_payment_processing(payment)
            
            if success:
                payment.status = "completed"
                payment.transaction_id = str(uuid.uuid4())
                payment.processed_at = datetime.utcnow()
                logger.info(f"Pago {payment_id} procesado exitosamente")
            else:
                payment.status = "failed"
                logger.warning(f"Pago {payment_id} falló")
            
            db.commit()
            db.refresh(payment)
            
            # Emitir evento si el pago fue exitoso
            if success:
                asyncio.create_task(self._emit_payment_processed_event(payment))
            
            return payment
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error procesando pago {payment_id}: {e}")
            raise
    
    def get_payment(self, db: Session, payment_id: int) -> Optional[Payment]:
        """Obtener un pago por ID"""
        return db.query(Payment).filter(Payment.id == payment_id).first()
    
    def get_payments_by_user(self, db: Session, user_id: int, skip: int = 0, limit: int = 10):
        """Obtener pagos de un usuario"""
        return db.query(Payment).filter(Payment.user_id == user_id).order_by(desc(Payment.created_at)).offset(skip).limit(limit).all()
    
    def get_all_payments(self, db: Session, skip: int = 0, limit: int = 100):
        """Obtener todos los pagos (para admin/debug)"""
        return db.query(Payment).order_by(desc(Payment.created_at)).offset(skip).limit(limit).all()
    
    def _simulate_payment_processing(self, payment: Payment) -> bool:
        """Simular el procesamiento del pago"""
        import random
        import time
        
        # Simular tiempo de procesamiento
        time.sleep(1)
        
        # Simular 95% de éxito en los pagos
        success_rate = 0.95
        
        # Factores que pueden afectar el éxito
        if payment.amount > 100:
            success_rate = 0.90  # Pagos más altos tienen menor tasa de éxito
        
        return random.random() < success_rate
    
    async def _emit_payment_processed_event(self, payment: Payment):
        """Emitir evento de pago procesado"""
        try:
            event_data = PaymentProcessedEvent(
                payment_id=payment.id,
                user_id=payment.user_id,
                plan_id=payment.plan_id,
                plan_name=payment.plan_name,
                amount=payment.amount,
                status=payment.status,
                transaction_id=payment.transaction_id,
                timestamp=datetime.utcnow()
            )
            
            await redis_client.publish_payment_processed(event_data.model_dump())
            logger.info(f"Evento PaymentProcessed emitido para pago {payment.id}")
            
        except Exception as e:
            logger.error(f"Error emitiendo evento PaymentProcessed: {e}")
    
    async def handle_plan_selected_event(self, db: Session, event_data: dict):
        """Manejar evento PlanSelected automáticamente"""
        try:
            user_id = int(event_data.get("user_id"))
            plan_id = int(event_data.get("plan_id"))
            
            logger.info(f"Procesando PlanSelected para usuario {user_id}, plan {plan_id}")
            
            # Crear PaymentRequest automático
            payment_request = PaymentRequest(
                plan_id=plan_id,
                payment_method="auto_payment"  # Pago automático desde evento
            )
            
            # Crear el pago
            payment = self.create_payment(db, user_id, payment_request)
            
            # Procesar el pago automáticamente
            processed_payment = self.process_payment(db, payment.id)
            
            if processed_payment and processed_payment.status == "completed":
                logger.info(f"Pago automático completado: {processed_payment.id}")
            else:
                logger.warning(f"Pago automático falló: {payment.id}")
                
        except Exception as e:
            logger.error(f"Error manejando evento PlanSelected: {e}")

# Instancia global del servicio
payment_service = PaymentService()