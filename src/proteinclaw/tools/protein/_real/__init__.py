"""Real (non-mock) tool backends.

Excluded from default coverage gating because most of these wrap external
infrastructure (REST APIs, GPU subprocesses) we cannot exercise in PR CI.
Tests under `tests/tools/_real/` cover the backend code paths that don't
require the live infrastructure (argument construction, output parsing,
HTTP request shape via mocks).
"""
