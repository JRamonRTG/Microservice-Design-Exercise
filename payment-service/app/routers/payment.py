from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from models import Payment, PaymentRequest, PaymentResponse, PaymentStatus, PLANS_INFO  # Agregado Payment
from services.payment_service import payment_service

router = APIRouter()

@router.get("/health")
async def health_check():
    """Endpoint de salud del servicio"""
    return {"status": "healthy", "service": "payment-service"}

@router.get("/plans")
async def get_available_plans():
    """Obtener planes disponibles"""
    return {"plans": PLANS_INFO}

@router.post("/payments/{user_id}", response_model=PaymentResponse)
async def create_payment(
    user_id: int,
    payment_request: PaymentRequest,
    db: Session = Depends(get_db)
):
    """Crear un nuevo pago para un usuario"""
    try:
        # Validar que el usuario existe (en un escenario real, consultaríamos el User Service)
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
        
        # Crear el pago
        payment = payment_service.create_payment(db, user_id, payment_request)
        return payment
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )

@router.post("/payments/{payment_id}/process", response_model=PaymentStatus)
async def process_payment(
    payment_id: int,
    db: Session = Depends(get_db)
):
    """Procesar un pago pendiente"""
    try:
        payment = payment_service.process_payment(db, payment_id)
        
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pago {payment_id} no encontrado"
            )
        
        return PaymentStatus(
            payment_id=payment.id,
            status=payment.status,
            transaction_id=payment.transaction_id,
            processed_at=payment.processed_at
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )

@router.get("/payments/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: int,
    db: Session = Depends(get_db)
):
    """Obtener información de un pago específico"""
    payment = payment_service.get_payment(db, payment_id)
    
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pago {payment_id} no encontrado"
        )
    
    return payment

@router.get("/users/{user_id}/payments", response_model=List[PaymentResponse])
async def get_user_payments(
    user_id: int,
    skip: int = 0,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """Obtener todos los pagos de un usuario"""
    if user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de usuario inválido"
        )
    
    payments = payment_service.get_payments_by_user(db, user_id, skip, limit)
    return payments

@router.get("/payments", response_model=List[PaymentResponse])
async def get_all_payments(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Obtener todos los pagos (para admin/debug)"""
    # Importamos Payment de models correctamente
    payments = payment_service.get_all_payments(db, skip, limit)  # Mejor usar el servicio
    return payments