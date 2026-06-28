import time
import httpx
import os
from abc import ABC, abstractmethod


RATE_LIMIT = float(os.environ.get("RATE_LIMIT", "1.0"))
_last_request_time: float = 0.0


def rate_limited_get(url: str, **kwargs) -> httpx.Response:
    global _last_request_time
    gap = 1.0 / RATE_LIMIT
    elapsed = time.time() - _last_request_time
    if elapsed < gap:
        time.sleep(gap - elapsed)
    _last_request_time = time.time()
    return httpx.get(url, **kwargs)


def rate_limited_request(method: str, url: str, **kwargs) -> httpx.Response:
    global _last_request_time
    gap = 1.0 / RATE_LIMIT
    elapsed = time.time() - _last_request_time
    if elapsed < gap:
        time.sleep(gap - elapsed)
    _last_request_time = time.time()
    return httpx.request(method, url, **kwargs)


class ScopeViolation(Exception):
    pass


class ScopeChecker:
    def __init__(self, allowed: list[str] | None = None):
        self.allowed = allowed or []

    def check(self, url: str) -> bool:
        if not self.allowed:
            return True
        return any(url.startswith(a) for a in self.allowed)


_global_scope = ScopeChecker()


def set_scope(urls: list[str]):
    _global_scope.allowed = urls


def checked_request(method: str, url: str, timeout: int = 30, **kwargs) -> httpx.Response:
    if not _global_scope.check(url):
        raise ScopeViolation(f"Out of scope: {url}")
    return rate_limited_request(method, url, timeout=timeout, follow_redirects=True, **kwargs)


class BaseTool(ABC):
    name: str = ""
    timeout: int = 30

    @abstractmethod
    def run(self, **kwargs) -> dict:
        ...

    def safe_run(self, **kwargs) -> dict:
        try:
            return self.run(**kwargs)
        except ScopeViolation as e:
            return {"error": f"Scope violation: {e}", "success": False}
        except Exception as e:
            return {"error": str(e), "success": False}
