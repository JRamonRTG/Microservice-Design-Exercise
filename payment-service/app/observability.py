
import json
import logging
import time
import uuid
import contextvars
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

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

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, header_name: str = "x-correlation-id"):
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get(self.header_name) or request.headers.get(self.header_name.upper())
        cid = incoming or str(uuid.uuid4())
        set_correlation_id(cid)
        request.state.correlation_id = cid
        try:
            response: Response = await call_next(request)
        except Exception:
            response = Response(status_code=500, content=b"")
            raise
        finally:
            try:
                response.headers[self.header_name] = cid
            except Exception:
                pass
            set_correlation_id(None)
        return response

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, logger: logging.Logger):
        super().__init__(app)
        self.logger = logger

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        method = request.method
        path = request.url.path
        query = str(request.url.query or "")
        client_ip = request.client.host if request.client else None
        ua = request.headers.get("user-agent")

        self.logger.info("http_request_start", extra={"extra": {
            "event": "http_request_start",
            "http.method": method, "http.path": path, "http.query": query,
            "client.ip": client_ip, "user_agent": ua,
        }})
        try:
            response: Response = await call_next(request)
            status = response.status_code
            dur = int((time.perf_counter() - start) * 1000)
            self.logger.info("http_request_end", extra={"extra": {
                "event": "http_request_end",
                "http.method": method, "http.path": path, "http.query": query,
                "http.status_code": status, "duration_ms": dur,
                "client.ip": client_ip, "user_agent": ua,
            }})
            return response
        except Exception as e:
            dur = int((time.perf_counter() - start) * 1000)
            self.logger.error(f"http_request_error: {e}", extra={"extra": {
                "event": "http_request_error",
                "http.method": method, "http.path": path, "http.query": query,
                "duration_ms": dur, "client.ip": client_ip, "user_agent": ua,
            }}, exc_info=True)
            raise
