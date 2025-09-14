
import json
import logging
import time
import uuid
import contextvars
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.datastructures import Headers

# Context var para correlación
_correlation_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("correlation_id", default=None)

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        base: Dict[str, Any] = {
            "ts": _now_iso(),
            "level": record.levelname,
            "service": self.service,
            "message": record.getMessage(),
        }
        cid = _correlation_id.get()
        if cid:
            base["correlation_id"] = cid
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            base.update(extra)
        if record.exc_info:
            base["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(base, ensure_ascii=False)

def init_logging(service_name: str, level: str = "INFO") -> logging.Logger:
    root = logging.getLogger()
    root.handlers = []
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter(service_name))
    root.addHandler(h)
    root.setLevel(level.upper())
    logging.getLogger("uvicorn.error").setLevel(level.upper())
    logging.getLogger("uvicorn.access").setLevel(level.upper())
    return logging.getLogger(service_name)

def set_correlation_id(cid: Optional[str]):
    _correlation_id.set(cid)

def get_correlation_id() -> Optional[str]:
    return _correlation_id.get()

class CorrelationIdASGIMiddleware:
    def __init__(self, app: ASGIApp, header_name: str = "x-correlation-id"):
        self.app = app
        self.header_name = header_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        incoming = headers.get(self.header_name) or headers.get(self.header_name.upper())
        cid = incoming or str(uuid.uuid4())
        token = _correlation_id.set(cid)

        started = {"value": False}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                started["value"] = True
                hdrs = list(message.get("headers", []))
                hdrs.append((b"x-correlation-id", cid.encode()))
                message["headers"] = hdrs
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # Si falló antes de enviar headers, enviamos un 500 JSON
            if not started["value"]:
                body = json.dumps({"detail": "Internal Server Error"}).encode()
                await send_wrapper({"type": "http.response.start", "status": 500, "headers": [(b"content-type", b"application/json")]})
                await send_wrapper({"type": "http.response.body", "body": body})
            # Si ya empezó, no podemos enviar cabeceras nuevas; en ese caso dejamos que el servidor cierre.
        finally:
            _correlation_id.reset(token)

class RequestLoggingASGIMiddleware:
    def __init__(self, app: ASGIApp, logger: logging.Logger):
        self.app = app
        self.logger = logger

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method")
        path = scope.get("path")
        query_string = scope.get("query_string", b"").decode() if scope.get("query_string") else ""
        client = scope.get("client")
        client_ip = client[0] if client else None
        start = time.perf_counter()

        self.logger.info("http_request_start", extra={"extra": {
            "event": "http_request_start",
            "http.method": method, "http.path": path, "http.query": query_string,
            "client.ip": client_ip,
        }})

        status_code = {"value": 200}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_code["value"] = message.get("status", 200)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
            dur = int((time.perf_counter() - start) * 1000)
            self.logger.info("http_request_end", extra={"extra": {
                "event": "http_request_end",
                "http.method": method, "http.path": path, "http.query": query_string,
                "http.status_code": status_code["value"], "duration_ms": dur,
                "client.ip": client_ip,
            }})
        except Exception as e:
            dur = int((time.perf_counter() - start) * 1000)
            self.logger.error(f"http_request_error: {e}", extra={"extra": {
                "event": "http_request_error",
                "http.method": method, "http.path": path, "http.query": query_string,
                "duration_ms": dur, "client.ip": client_ip,
            }}, exc_info=True)
            raise
