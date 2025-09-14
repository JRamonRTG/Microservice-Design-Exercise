
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
import logging

from app.database import get_db
from app.services.payment_service import payment_service
from app.models import PaymentResponse, PLANS_INFO
from app.observability import get_correlation_id

logger = logging.getLogger(__name__)
router = APIRouter()

class PaymentReq(BaseModel):
    plan_id: int

@router.post("/payments/{user_id}", response_model=PaymentResponse)
def create_and_process_payment(user_id: int, req: PaymentReq, request: Request, db: Session = Depends(get_db)):
    cid = get_correlation_id()  # del middleware
    try:
        plan = PLANS_INFO.get(req.plan_id)
        if not plan:
            raise HTTPException(status_code=400, detail="Plan inválido")

        pay = payment_service.create_payment(db, user_id=user_id, plan_id=req.plan_id)
        pay = payment_service.process_payment(db, pay)

        logger.info("api_payment_completed", extra={"extra": {
            "event": "api_payment_completed",
            "user_id": user_id, "payment_id": pay.id,
            "correlation_id": cid
        }})
        return PaymentResponse.model_validate(pay, from_attributes=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"create_and_process_payment error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/payments", response_model=list[PaymentResponse])
def list_by_user(user_id: int, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    try:
        items = payment_service.get_payments_by_user(db, user_id=user_id, skip=skip, limit=limit)
        return [PaymentResponse.model_validate(p, from_attributes=True) for p in items]
    except Exception as e:
        logger.error(f"list_by_user error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
