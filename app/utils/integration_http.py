"""
Shared HTTP session for outbound integration calls (retries, timeouts).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = (5, 30)


def integration_session(
    total_retries: int = 3,
    backoff_factor: float = 0.5,
    timeout: tuple = _DEFAULT_TIMEOUT,
) -> requests.Session:
    """
    Session with retry on 429, 500, 502, 503, 504 for GET/POST/PUT/PATCH/DELETE.
    """
    session = requests.Session()
    retry = Retry(
        total=total_retries,
        connect=total_retries,
        read=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=20)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.request_timeout = timeout  # type: ignore[attr-defined]
    return session


def session_request(
    session: requests.Session,
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json: Any = None,
    data: Any = None,
    timeout: Optional[tuple] = None,
) -> requests.Response:
    """Perform request using session's default timeout."""
    to = timeout or getattr(session, "request_timeout", _DEFAULT_TIMEOUT)
    return session.request(method.upper(), url, headers=headers, params=params, json=json, data=data, timeout=to)
