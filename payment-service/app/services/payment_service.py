# payment-service/app/services/payment_service.py
import uuid, logging, json
from datetime import datetime
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import select, desc
import redis  # ⬅ para capturar errores de conexión/timeout

from app.models import Payment, PaymentRequest, PaymentResponse, PaymentStatus, PLANS_INFO, PaymentProcessedEvent
from app.redis_client import get_client, STREAM_OUT
from app.observability import get_correlation_id
from app.resilience import record_publish_success, record_publish_failure  # ⬅ NUEVO

logger = logging.getLogger(__name__)

class PaymentService:
    def create_payment(self, db: Session, user_id: int, plan_id: int) -> Payment:
        plan = PLANS_INFO.get(plan_id)
        if not plan:
            raise ValueError("Plan inválido")
        payment = Payment(
            user_id=user_id,
            plan_id=plan_id,
            plan_name=plan["name"],
            amount=plan["price"],
            status="pending",
        )
        db.add(payment)
        db.commit()
        db.refresh(payment)
        return payment

    def process_payment(self, db: Session, payment: Payment) -> Payment:
        payment.status = "completed"
        payment.transaction_id = uuid.uuid4().hex[:16]
        db.commit()
        db.refresh(payment)

        evt = PaymentProcessedEvent(
            payment_id=payment.id,
            user_id=payment.user_id,
            status=payment.status,
            amount=payment.amount,
            transaction_id=payment.transaction_id,
            timestamp=datetime.utcnow(),
        )

        data = json.loads(evt.model_dump_json())  # serializa datetime -> ISO
        data["event"] = "PaymentProcessed"

        cid = get_correlation_id()
        if cid:
            data["correlation_id"] = cid

        try:
            r = get_client()
            r.xadd(STREAM_OUT, {"data": json.dumps(data, ensure_ascii=False)})
            logger.info("PaymentProcessed emitted", extra={"extra": {
                "event": "payment_processed_emitted",
                "payment_id": payment.id,
                "user_id": payment.user_id,
                "correlation_id": cid
            }})
            record_publish_success(cid)  # ⬅ registra éxito
        except (redis.exceptions.TimeoutError, redis.exceptions.ConnectionError) as e:
            logger.warning("publish_payment_event_timeout", extra={"extra": {
                "event": "publish_payment_event_timeout",
                "payment_id": payment.id,
                "user_id": payment.user_id,
                "error": str(e),
                "correlation_id": cid
            }})
            record_publish_failure(e, cid)  # ⬅ registra fallo
        except Exception as e:
            logger.error(f"publish_payment_event_error: {e}", extra={"extra": {
                "event": "publish_payment_event_error",
                "payment_id": payment.id,
                "user_id": payment.user_id,
                "correlation_id": cid
            }}, exc_info=True)
            record_publish_failure(e, cid)  # ⬅ registra fallo

        return payment

    def get_payments_by_user(self, db: Session, user_id: int, skip: int = 0, limit: int = 100) -> List[Payment]:
        stmt = select(Payment).where(Payment.user_id == user_id).order_by(desc(Payment.created_at)).offset(skip).limit(limit)
        return list(db.scalars(stmt))

    def get_all(self, db: Session, skip: int = 0, limit: int = 100) -> List[Payment]:
        stmt = select(Payment).order_by(desc(Payment.created_at)).offset(skip).limit(limit)
        return list(db.scalars(stmt))

    def get(self, db: Session, payment_id: int) -> Optional[Payment]:
        return db.get(Payment, payment_id)

payment_service = PaymentService()
