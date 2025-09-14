# Payment Service (FastAPI + PostgreSQL + Redis Streams)

Servicio de pagos para FitFlow. Escucha eventos `PlanSelected` desde Redis Streams 
y emite `PaymentProcessed` al completar el pago. Persiste pagos en PostgreSQL.

## Ejecutar en local con Docker Compose

```bash
cd fixed-payment-service
cp .env.example .env
docker compose -f docker-compose.local.yml up --build
```
