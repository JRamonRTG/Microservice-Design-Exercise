import json
import logging
import time
import uuid
import contextvars
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import os
import jwt  # PyJWT

# Context vars
_correlation_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("correlation_id", default=None)
_user_id_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("user_id", default=None)

def set_user_id(uid: Optional[str]):
    _user_id_ctx.set(uid)

def get_user_id() -> Optional[str]:
    return _user_id_ctx.get()

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
        uid = _user_id_ctx.get()
        if uid:
            base["auth_user_id"] = uid
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

def set_user_id(uid: Optional[str]):
    _user_id_ctx.set(uid)

def get_user_id() -> Optional[str]:
    return _user_id_ctx.get()

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
        finally:
            # 🆕 Header de debug (si hay JWT válido)
            uid = get_user_id()
            if uid:
                response.headers["x-user-id-from-jwt"] = uid

            try:
                response.headers[self.header_name] = cid
            except Exception:
                pass
            set_correlation_id(None)
            set_user_id(None)
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

        self.logger.info("HTTP request start", extra={"extra": {
            "event": "http_request_start",
            "http.method": method, "http.path": path, "http.query": query,
            "client.ip": client_ip, "user_agent": ua,
            # 🆕 visible desde el inicio si el token ya vino
            "auth_user_id": get_user_id()
        }})
        try:
            response: Response = await call_next(request)
            status = response.status_code
            dur = int((time.perf_counter() - start) * 1000)
            self.logger.info("HTTP request end", extra={"extra": {
                "event": "http_request_end",
                "http.method": method, "http.path": path, "http.query": query,
                "http.status_code": status, "duration_ms": dur,
                "client.ip": client_ip, "user_agent": ua,
                "auth_user_id": get_user_id()
            }})
            return response
        except Exception as e:
            dur = int((time.perf_counter() - start) * 1000)
            self.logger.error(f"HTTP request error: {e}", extra={"extra": {
                "event": "http_request_error",
                "http.method": method, "http.path": path, "http.query": query,
                "duration_ms": dur, "client.ip": client_ip, "user_agent": ua,
            }}, exc_info=True)
            raise

class JwtUserMiddleware(BaseHTTPMiddleware):
    """
    Lee Authorization: Bearer <JWT>, lo valida (si viene) y expone user_id en contexto/logs.
    NO rechaza la request si falta o es inválido: sólo no setea user_id (autenticación no obligatoria).
    """
    def __init__(self, app):
        super().__init__(app)
        self.alg = os.getenv("JWT_ALG", "HS256")
        self.secret = os.getenv("JWT_SECRET")
        self.pub_path = os.getenv("JWT_PUBLIC_KEY_PATH")

        # Carga clave pública si usamos RS256
        self.public_key = None
        if self.alg.startswith("RS") and self.pub_path and os.path.exists(self.pub_path):
            with open(self.pub_path, "r", encoding="utf-8") as f:
                self.public_key = f.read()

    async def dispatch(self, request: Request, call_next):
        try:
            auth = request.headers.get("authorization") or request.headers.get("Authorization")
            if auth and auth.lower().startswith("bearer "):
                token = auth.split(" ", 1)[1].strip()
                claims = None
                if self.alg.startswith("RS"):
                    if self.public_key:
                        claims = jwt.decode(token, self.public_key, algorithms=[self.alg], options={"verify_aud": False})
                else:
                    if self.secret:
                        claims = jwt.decode(token, self.secret, algorithms=[self.alg], options={"verify_aud": False})

                if claims:
                    uid = str(claims.get("sub") or claims.get("user_id") or "")
                    if uid:
                        set_user_id(uid)
        except Exception:
            # No tiramos la request por token inválido: sólo omitimos user_id
            pass

        return await call_next(request)
