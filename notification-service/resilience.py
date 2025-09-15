# notification-service/resilience.py
from collections import deque
from threading import Lock
from datetime import datetime, timezone
from typing import Optional, Dict, Any

class _ResilienceState:
    def __init__(self, max_events: int = 100):
        self._lock = Lock()
        # Contadores del consumidor de Redis (payment_events)
        self.consume_success = 0
        self.consume_fail = 0
        self.consecutive_consume_failures = 0
        self.last_consume_success: Optional[str] = None
        self.last_consume_error: Optional[Dict[str, Any]] = None
        self.events = deque(maxlen=max_events)  # ring buffer de eventos de resiliencia

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def record_consume_success(self, correlation_id: Optional[str] = None):
        now = self._now()
        with self._lock:
            self.consume_success += 1
            self.consecutive_consume_failures = 0
            self.last_consume_success = now
            self.events.append({
                "ts": now, "type": "consume_success",
                "correlation_id": correlation_id
            })

    def record_consume_failure(self, error: str, correlation_id: Optional[str] = None):
        now = self._now()
        with self._lock:
            self.consume_fail += 1
            self.consecutive_consume_failures += 1
            self.last_consume_error = {"ts": now, "error": error}
            self.events.append({
                "ts": now, "type": "consume_failure",
                "error": error, "correlation_id": correlation_id
            })

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "consume_success": self.consume_success,
                "consume_fail": self.consume_fail,
                "consecutive_consume_failures": self.consecutive_consume_failures,
                "last_consume_success": self.last_consume_success,
                "last_consume_error": self.last_consume_error,
                "recent": list(self.events),
            }

_state = _ResilienceState()

def record_consume_success(correlation_id: Optional[str] = None):
    _state.record_consume_success(correlation_id)

def record_consume_failure(error: Exception | str, correlation_id: Optional[str] = None):
    _state.record_consume_failure(str(error), correlation_id)

def get_snapshot() -> Dict[str, Any]:
    return _state.snapshot()
