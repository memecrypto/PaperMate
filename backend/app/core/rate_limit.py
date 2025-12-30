import time
from collections import deque
from threading import Lock
from typing import Deque

from fastapi import Request

from app.core.config import get_settings

settings = get_settings()


class InMemoryRateLimiter:
    """Simple in-memory rate limiter for login attempts."""

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, Deque[float]] = {}
        self._lock = Lock()

    def _prune(self, attempts: Deque[float], now: float) -> None:
        while attempts and now - attempts[0] > self.window_seconds:
            attempts.popleft()

    def is_blocked(self, key: str) -> bool:
        if not key or self.max_attempts <= 0:
            return False
        now = time.monotonic()
        with self._lock:
            attempts = self._attempts.get(key)
            if not attempts:
                return False
            self._prune(attempts, now)
            if not attempts:
                self._attempts.pop(key, None)
                return False
            return len(attempts) >= self.max_attempts

    def record_failure(self, key: str) -> None:
        if not key or self.max_attempts <= 0:
            return
        now = time.monotonic()
        with self._lock:
            attempts = self._attempts.setdefault(key, deque())
            self._prune(attempts, now)
            attempts.append(now)

    def reset(self, key: str) -> None:
        if not key:
            return
        with self._lock:
            self._attempts.pop(key, None)


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
        if ip:
            return ip
    if request.client:
        return request.client.host or "unknown"
    return "unknown"


login_ip_limiter = InMemoryRateLimiter(
    settings.login_rate_limit_per_ip,
    settings.login_rate_limit_window_seconds,
)
login_user_limiter = InMemoryRateLimiter(
    settings.login_rate_limit_per_user,
    settings.login_rate_limit_window_seconds,
)
