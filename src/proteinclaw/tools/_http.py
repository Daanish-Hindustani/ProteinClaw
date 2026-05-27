"""Tiny HTTP helpers used by every plain-Python tool.

Centralised so that every outbound request has the same User-Agent (helps
API operators rate-limit politely) and the same default timeout. Errors are
*not* swallowed here — each tool decides whether a network failure is fatal
or a graceful degradation (PRD §10.2).
"""

from __future__ import annotations

import time
from typing import Any, Optional

import requests

USER_AGENT = "proteinclaw/0.1 (+https://github.com/Daanish-Hindustani/ProteinClaw)"
DEFAULT_TIMEOUT_S = 20.0

# Statuses we treat as transient and retry on (matches celltype-agent's
# http_client._RETRYABLE_STATUS). 429 = rate-limit, 5xx = server hiccup.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def get_json(
    url: str,
    *,
    params: Optional[dict[str, Any]] = None,
    session: Optional[requests.Session] = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    headers: Optional[dict[str, str]] = None,
) -> tuple[int, Any]:
    """GET ``url`` and parse JSON. Returns ``(status_code, parsed_or_text)``.

    Connection errors raise; HTTP error statuses do not (the caller decides).
    """
    sess = session or make_session()
    resp = sess.get(url, params=params, timeout=timeout, headers=headers)
    ct = resp.headers.get("Content-Type", "")
    if "application/json" in ct or resp.text.lstrip().startswith(("{", "[")):
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, resp.text
    return resp.status_code, resp.text


def post_json(
    url: str,
    *,
    payload: Any,
    session: Optional[requests.Session] = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    headers: Optional[dict[str, str]] = None,
) -> tuple[int, Any]:
    sess = session or make_session()
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    resp = sess.post(url, json=payload, timeout=timeout, headers=h)
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, resp.text


def get_text(
    url: str,
    *,
    params: Optional[dict[str, Any]] = None,
    session: Optional[requests.Session] = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    headers: Optional[dict[str, str]] = None,
) -> tuple[int, str]:
    sess = session or make_session()
    resp = sess.get(url, params=params, timeout=timeout, headers=headers)
    return resp.status_code, resp.text


def post_form(
    url: str,
    *,
    data: dict[str, Any],
    session: Optional[requests.Session] = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    headers: Optional[dict[str, str]] = None,
) -> tuple[int, str]:
    sess = session or make_session()
    resp = sess.post(url, data=data, timeout=timeout, headers=headers)
    return resp.status_code, resp.text


def get_json_with_retry(
    url: str,
    *,
    params: Optional[dict[str, Any]] = None,
    session: Optional[requests.Session] = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    headers: Optional[dict[str, str]] = None,
    retries: int = 2,
    backoff_seconds: float = 0.5,
) -> tuple[int, Any]:
    """``get_json`` with exponential backoff on 429 / 5xx and network errors.

    Pattern matches celltype-agent's request helper: up to ``retries`` extra
    attempts (3 total by default), delay doubles each pass (0.5s → 1s → 2s).
    Caller still decides how to interpret the final status — we don't raise
    for HTTP errors, just retry the transient ones.
    """
    sess = session or make_session()
    delay = max(backoff_seconds, 0.0)
    last_exc: Optional[Exception] = None
    last_status, last_body = 0, None
    for attempt in range(max(retries, 0) + 1):
        try:
            status, body = get_json(
                url, params=params, session=sess, timeout=timeout, headers=headers
            )
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise
        last_status, last_body = status, body
        if status in _RETRYABLE_STATUS and attempt < retries:
            time.sleep(delay)
            delay *= 2
            continue
        return status, body
    if last_exc is not None:
        raise last_exc
    return last_status, last_body


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "USER_AGENT",
    "get_json",
    "get_json_with_retry",
    "get_text",
    "make_session",
    "post_form",
    "post_json",
]
