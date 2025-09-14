# FitFlow – Infra local (3 microservicios)

Estructura esperada:
/user-service
/payment-service
/notification-service
/infra  <-- esta carpeta

## Levantar todo
cd infra
docker compose up --build

## Salud
User:         http://localhost:8001/health
Payment:      http://localhost:8002/health
Notification: http://localhost:8003/health

## Flujo de prueba
# 1) Registrar usuario
curl -X POST http://localhost:8001/users/register -H "Content-Type: application/json" -d '{"name":"Ana","email":"ana@example.com","password":"secret"}'

# 2) Seleccionar plan (debe publicar PlanSelected a Redis)
curl -X POST http://localhost:8001/users/1/select-plan -H "Content-Type: application/json" -d '{"plan_id":2}'

# 3) Ver pagos
curl "http://localhost:8002/payments?user_id=1"

# 4) Ver notificaciones
curl "http://localhost:8003/notifications"

# Si aún no publica, simula evento:
redis-cli XADD user_events * data '{"event":"PlanSelected","user_id":1,"plan_id":2,"plan_name":"Plan Estándar"}'
