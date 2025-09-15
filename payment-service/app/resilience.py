# payment-service/app/resilience.py
from collections import deque
from threading import Lock
from datetime import datetime, timezone
from typing import Optional, Dict, Any

class _ResilienceState:
    def __init__(self, max_events: int = 100):
        self._lock = Lock()
        self.publish_success = 0
        self.publish_fail = 0
        self.consecutive_failures = 0
        self.last_success: Optional[str] = None
        self.last_error: Optional[Dict[str, Any]] = None
        self.events = deque(maxlen=max_events)  # ring buffer

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def record_success(self, correlation_id: Optional[str] = None):
        now = self._now()
        with self._lock:
            self.publish_success += 1
            self.consecutive_failures = 0
            self.last_success = now
            self.events.append({
                "ts": now, "type": "publish_success",
                "correlation_id": correlation_id
            })

    def record_failure(self, error: str, correlation_id: Optional[str] = None):
        now = self._now()
        with self._lock:
            self.publish_fail += 1
            self.consecutive_failures += 1
            self.last_error = {"ts": now, "error": error}
            self.events.append({
                "ts": now, "type": "publish_failure",
                "error": error, "correlation_id": correlation_id
            })

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "publish_success": self.publish_success,
                "publish_fail": self.publish_fail,
                "consecutive_failures": self.consecutive_failures,
                "last_success": self.last_success,
                "last_error": self.last_error,
                "recent": list(self.events),
            }

_state = _ResilienceState()

def record_publish_success(correlation_id: Optional[str] = None):
    _state.record_success(correlation_id)

def record_publish_failure(error: Exception | str, correlation_id: Optional[str] = None):
    _state.record_failure(str(error), correlation_id)

def get_snapshot() -> Dict[str, Any]:
    return _state.snapshot()
