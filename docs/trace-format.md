# Trace Format

> Stub. Initial shape lives in `src/proteinclaw/common/logging.py::TraceEvent`.

Every event is immutable, JSON-serializable, and identified by `event_id` + `timestamp`. Replaying events in order from the Trace Store must reconstruct the session — this is a correctness requirement.

Canonical event kinds are enumerated in `EventKind`. New kinds are added there, never as inline strings.
