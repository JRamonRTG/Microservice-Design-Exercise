## Observabilidad

**Objetivo:** que cualquiera pueda seguir una flujo o un evento de punta a punta sin perderse, entendiendo qué pasó, dónde y con qué usuario.

**Qué implementamos y por qué:**

- **Correlation ID en todo el flujo**: cada flujo o evento se pasa con un `x-correlation-id`. Si no viene el middleware lo genera. Esto permite reconstruir el historial completo cuando `user-service` publica un evento que procesa `payment-service` y luego termina como notificación en `notification-service`. El beneficio es diagnóstico rápido sin buscar “a mano” entre miles de logs.
- **Logs JSON estructurados**: todos los servicios escriben logs con un mismo formato: tiempo, nombre del servicio, nivel, tipo de evento, correlation id, duración estimada y, si el token venía en la flujo, el `auth_user_id`. Elegimos JSON porque facilita filtros.
- **Validación JWT para trazas**: sólo `user-service` emite tokens. En `payment` y `notification` se validan para el `auth_user_id` en los logs. No bloqueamos tráfico por falta de token en esta etapa para no complicar demos ni tests; el objetivo aquí es **visibilidad**.
- **Puntos de diagnóstico ligeros**: cada servicio expone endpoints de salud y un resumen de contadores internos (por ejemplo cuántos eventos se publicaron o consumieron y cuántos fallaron). Esto nos da cómo va el sistema sin abrir el código ni montar dashboards pesados.

## Resiliencia & Registry

**Objetivo:** que el sistema se mantenga estable frente a fallos temporales (latencias, microcortes, picos) y que los servicios se encuentren.

**Qué implementamos y por qué:**

- **Timeouts cortos en dependencias**: todo lo que habla con algo externo (Azure SQL, Azure PostgreSQL, Redis) tiene tiempos de espera reducidos. Es preferible fallar rápido y registrar el motivo a colgar el servicio. Esto evita cascadas de errores y nos permite decidir si reintentamos.
- **Reintentos con backoff controlado**: al publicar o consumir eventos usamos reintentos suaves. La idea es superar microcortes sin saturar el sistema ni duplicar efectos. Están acotados para evitar loops infinitos.
- **Backpressure e idempotencia en consumo**: consumimos en lotes pequeños y asumimos que un mensaje puede llegar dos veces. Por eso el diseño considera reconocer correctamente los mensajes y, si vemos el mismo `transaction_id`, evitar reprocesar. Esto protege de pagos duplicados y de “efectos secundarios” repetidos.
- **Health/Readiness**: cada servicio declara si está vivo y si sus dependencias responden, lo que ayuda tanto en local como en ambientes de nube a decidir cuándo recibir tráfico.
- **Service discovery**: en local, Docker Compose nos da DNS de servicios; en Azure Container Apps el enrutamiento lo maneja el ambiente. No se usan IPs hardcodeadas y se documentan nombres/hosts para que movernos de local a nube sea natural.

## Seguridad

**Objetivo:** proteger datos y credenciales sin frenar la velocidad del equipo, dejando espacio para endurecer políticas cuando el proyecto avance.

**Qué implementamos y por qué:**

- **JWT centralizado en `user-service`**: sólo este servicio emite el token. Los demás pueden leerlo para los logs (y más adelante si queremos exigirlo). Con esto mantenemos una única fuente de verdad para la autenticación y evitamos definir firmas distintas por servicio.
- **Principio de menor privilegio en bases de datos**: cada servicio usa credenciales y alcances propios para no tener todos permisos, a demas de que estan en diferentes bases de datos.
  - `user-service` → Azure SQL (base `user_db`) con un usuario contenido que sólo puede leer/escribir lo suyo.
  - `payment-service` → Azure PostgreSQL (base `fitflow_payments`) con un rol propio y un esquema dedicado (`payments`) del que es propietario.
  - `notification-service` → por ahora no persiste en DB; si en el futuro lo hace, tendrá su propia base/rol con permisos mínimos.
  Esta separación reduce el impacto de un posible incidente: un servicio comprometido no puede tocar datos ajenos.
- **Gestión de secretos real**: credenciales y llaves se cargan por variables de entorno/secretos del runtime (por ejemplo, Azure Container Apps o Key Vault). Esto para rotar secretos sin recompilar ni exponerlos en el repo.
- **Cifrado en tránsito por defecto**: Redis con TLS, SQL Server con cifrado habilitado y PostgreSQL con SSL requerido. En nube, muchas rutas salen del contenedor, así que asumimos que **todo viaje cifrado** desde el inicio.



# FitFlow – (3 microservicios)

Estructura :
/user-service
/payment-service
/notification-service
/infra (donde se maneja la infraestructura)

para en dado caso de Docker, se usa el siguiente flujo:

# levantar dbs
docker compose up -d redis sqlserver postgres-payment

# crear db
docker run --rm --network infra_default mcr.microsoft.com/mssql-tools ^
  /opt/mssql-tools/bin/sqlcmd -S tcp:fitflow-sqlserver,1433 -U sa -P "YourStrong!Passw0rd" ^
  -Q "IF DB_ID('user_db') IS NULL CREATE DATABASE user_db;"

# levantar servicios
docker compose up --build -d user-service payment-service notification-service

# Salud
User:         http://localhost:8001/health
Payment:      http://localhost:8002/health
Notification: http://localhost:8003/health

# 1) Registrar usuario y logearse
curl -X POST http://localhost:8001/users/register ^
  -H "Content-Type: application/json" ^
  -d "{\"name\":\"Beto\",\"email\":\"beto+e2e@example.com\",\"password\":\"secret\"}"

curl -X POST http://localhost:8001/login ^
  -H "Content-Type: application/json" ^
  -d "{\"email\":\"beto+e2e@example.com\",\"password\":\"secret\"}"

# 2) Seleccionar plan (debe publicar PlanSelected a Redis)
curl -H "Authorization: Bearer %TOKEN%" ^
     -H "x-correlation-id: demo-001" ^
     -H "Content-Type: application/json" ^
     -X POST http://localhost:8001/users/1/select-plan ^
     -d "{\"plan_id\":2,\"plan_name\":\"Plan Estándar\"}"

# 3) Ver pagos
curl "http://localhost:8002/payments?user_id=1"

# 4) Ver notificaciones
curl "http://localhost:8003/notifications"


# logs y comandos asociados
docker logs --tail 100 fitflow-user-service
docker logs --tail 100 fitflow-notification-service

# observabilidad
docker logs -f fitflow-user-service | findstr /i "demo-001"
docker logs -f fitflow-notification-service | findstr /i "demo-001"

# comandos de resiliencia y diagnostico por microservicio
curl http://localhost:8001/resilience
curl http://localhost:8002/resilience
curl http://localhost:8003/resilience

curl http://localhost:8001/diag
curl http://localhost:8002/diag
curl http://localhost:8003/diag

## entonces, para los eventos tendriamos esquemas como estos:
PlanSelected (user → payment)

{
  "event": "PlanSelected",
  "user_id": 1,
  "plan_id": 2,
  "plan_name": "Plan Estándar",
  "correlation_id": "demo-001",
  "timestamp": "2025-09-22T03:49:13Z"
}


PaymentProcessed (payment → notification)
{
  "event": "PaymentProcessed",
  "payment_id": 25,
  "user_id": 1,
  "plan_id": 2,
  "plan_name": "Plan Estándar",
  "status": "completed",
  "amount": 49.99,
  "transaction_id": "abcd1234",
  "correlation_id": "demo-001",
  "timestamp": "2025-09-22T03:50:32Z"
}

# Endpoints 

| Servicio     | Método | Ruta                            | Descripción                               |
| ------------ | ------ | ------------------------------- | ----------------------------------------- |
| user         | POST   | `/users/register`               | Crea usuario (SQL Server).                |
| user         | POST   | `/login`                        | Emite JWT.                                |
| user         | POST   | `/users/{id}/select-plan`       | Inserta selección + emite `PlanSelected`. |
| payment      | POST   | `/payments/{user_id}`           | (testing) Crea pago + `PaymentProcessed`. |
| payment      | GET    | `/payments?user_id=`            | Lista pagos (Postgres).                   |
| notification | GET    | `/notifications`                | Lista notificaciones in-memory.           |
| todos        | GET    | `/health` `/diag` `/resilience` | Salud, dependencias y métricas.           |


repositorio de github:
https://github.com/JRamonRTG/Microservice-Design-Exercise.git