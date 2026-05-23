"""Tiny HTTP helpers used by every plain-Python tool.

Centralised so that every outbound request has the same User-Agent (helps
API operators rate-limit politely) and the same default timeout. Errors are
*not* swallowed here — each tool decides whether a network failure is fatal
or a graceful degradation (PRD §10.2).
"""

from __future__ import annotations

from typing import Any, Optional

import requests

USER_AGENT = "proteinclaw/0.1 (+https://github.com/Daanish-Hindustani/ProteinClaw)"
DEFAULT_TIMEOUT_S = 20.0


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


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "USER_AGENT",
    "get_json",
    "get_text",
    "make_session",
    "post_form",
    "post_json",
]
