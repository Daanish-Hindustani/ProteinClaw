# NOTES.md — Cross-session engineering notebook

**Purpose:** A persistent, append-only log of fixes, gotchas, decisions, and important context that future Claude Code sessions (or human teammates) need to understand prior work. This is **the** place to leave breadcrumbs for the next session.

**Audience:** future-you, future Claude, future teammate. Assume they have **zero** memory of the current session.

---

## When to write here

Write a new entry when any of these happen:

- **A non-obvious fix** that the next person would otherwise re-debug from scratch.
- **A gotcha or footgun** you hit (and ideally how to spot it earlier next time).
- **A decision** that isn't captured in the PRD, ARCHITECTURE, or PLAN — and that someone could reasonably reverse without realising why it was made.
- **A workaround** for a tool / dep / API quirk (with the upstream issue link if any).
- **A partial implementation** — what's stubbed, what's untested, what's known-broken. Be honest (CLAUDE.md "Honesty about implementation state").
- **A pinned version** that matters (e.g. "dgl must be 2.0.0 for the RFD3 image; 2.1+ breaks SE3Transformer build").
- **A failed approach** that looked reasonable but didn't work. Saves the next person an hour.

**Do not** write here for:

- Things already in the PRD, ARCHITECTURE, PLAN, or CLAUDE — link to them instead.
- Routine status updates ("finished Task 2"). The git log is for that.
- Active debugging in progress — that goes in `DEBUG.md` (per CLAUDE.md "Debug workflow") and only moves here once resolved.

---

## Entry format

Append entries to the bottom of the relevant section. **Never rewrite or delete past entries** — strike through with `~~text~~` and add a follow-up entry if something is later found to be wrong.

```markdown
### YYYY-MM-DD — <short title>
**Context:** what was being worked on / what triggered this note
**Finding / Decision / Fix:** the thing the next person needs to know
**Why it matters:** what breaks or wastes time if this is forgotten
**Links:** commit SHA, PR #, file:line, DEBUG.md entry, upstream issue
```

Keep entries tight — one screen max per entry. If something needs a long writeup, link out to a dedicated doc.

---

## Sections

Group by area so the file stays navigable as it grows. Add a new section when the existing ones don't fit.

### Tooling & environment

(Docker, CUDA, drivers, conda/uv, weight caches, host setup.)

_No entries yet._

### Tool wrappers (4-file convention)

(RFdiffusion3, ProteinMPNN, ESMFold, AF2-multimer — including dep pins, weight-download quirks, parameter footguns.)

_No entries yet._

### Plain-Python tools

(UniProt, PDB, RCSB, Semantic Scholar, DuckDuckGo — API quirks, rate limits, fixture recipes.)

_No entries yet._

### Agent core & skill file

(Gemini loop, sandbox, `proteindesign.md` behavioral notes, trace format.)

_No entries yet._

### Runner / router

(Docker dispatch, VRAM checks, session workspace layout.)

_No entries yet._

### Persistence & reporting

(SQLite schema migrations, report.html quirks.)

_No entries yet._

### Cross-cutting / process

(Decisions about workflow, testing strategy, doc structure that future sessions should respect.)

#### 2026-05-23 — NOTES.md created
**Context:** Project still in Phase 0; PRD, ARCHITECTURE, PLAN, README, CLAUDE all written. No source code yet.
**Decision:** This file is the canonical cross-session notebook. Every future Claude Code session (and every agent in this repo) is expected to read it at session start and append to it when surfacing anything non-obvious. CLAUDE.md updated to require this.
**Why it matters:** Without it, each new session has to re-derive every gotcha from git log + code reading, which is slow and lossy.
**Links:** `CLAUDE.md` "Session memory" section.
