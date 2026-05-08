# Skill Format

Skills are *data*, not code. They live as Markdown files under
`src/proteinclaw/skills/protein_design/` with a YAML front-matter block
describing identity and applicability. The Evolution Service rewrites
them via patch-or-rewrite in Phase 7; each edit increments `version`
and links back through `parent_version` so the Trace Store can show the
lineage of every active skill.

## File layout

```markdown
---
id: binder_design
version: 2
name: Binder Design
description: De novo protein binder design against a target structure.
applicable_tasks: [binder_design]
provenance: human_authored
parent_version: 1
---

## Goal

(Markdown body — workflow steps, examples, pitfalls.)
```

## Schema

<!-- AUTO-GENERATED:skill-schema (source: src/proteinclaw/skills/skill.py::Skill) -->

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | `str` | Yes | Stable identifier shared across versions (e.g. `binder_design`). |
| `version` | `int ≥ 1` | Yes | Monotonically increasing per `id`; 1 for the first version. |
| `name` | `str` | Yes | Human-readable label. |
| `description` | `str` | Yes | Short summary surfaced to the planner. |
| `applicable_tasks` | `tuple[str, ...]` | No (default `()`) | Task tags this skill applies to. Used by `SkillLibrary.find_for(task_type)`. |
| `provenance` | `SkillProvenance` | Yes | `human_authored` or `evolved`. |
| `parent_version` | `int \| None` | No (default `null`) | Previous version this was patched from, or `null` for initial human-authored versions. Must be `< version`. |
| `examples` | `tuple[SkillExample, ...]` | No (default `()`) | Optional worked examples (description + inputs + outputs dicts). |
| `body` | `str` | Yes | Markdown body with the workflow steps. Sourced from the file content after the front-matter. |

The model is `frozen=True, extra="forbid"`. The Markdown body is parsed
out of the file by `parse_markdown_skill()` and assigned to the `body`
field — front-matter must NOT contain a `body:` key.

`Skill.version_id` (computed): formatted as `{id}@v{version}`. This is
what `BranchResult.skill_version_id` records.

<!-- /AUTO-GENERATED:skill-schema -->

## Validation

Every skill — human-authored or agent-authored — must pass
`SkillValidator.validate()` before entering the library.

Validator checks:

- **Schema** — Pydantic enforces field types + `extra="forbid"`.
- **Threat patterns** (regex over the body):
  - `threat.ignore_instructions` — "ignore previous/all/prior instructions/rules"
  - `threat.disregard` — "disregard any/all/the prior/above/previous"
  - `threat.system_role_redefinition` — role-redefinition phrases
  - `threat.system_tag` — `<system>`, `<admin>`, `<sudo>`, `<root>` tags
  - `threat.raw_credentials` — `api_key=`, `password=`, `secret=`, `token=` followed by a long value
- **Structural**:
  - `structure.empty_body` — body must contain non-whitespace.
  - `structure.bad_lineage` — `parent_version` must be `< version`.

`SkillValidationError` carries every issue at once so callers can surface
them all in one message.

## Editing actions (Phase 7)

`SkillManager` actions, mirroring the Hermes pattern:

- `create` — register a new id at `version=1`, `provenance=human_authored`.
- `edit` — replace the body of an existing version.
- `patch` — targeted find-and-replace (default for evolved skills; cheaper for the optimizer).
- `delete` — drop a version (audit-logged).

`patch` is the primary action for the Evolution Service because
Feedback Descent's reflective mutations tend to be small directional
edits, not full rewrites.

## Seed skills

Four versions live in the repo today (all v2, human-authored,
`parent_version: 1`):

- `binder_design` — de novo binder design with hotspot guidance.
- `enzyme_design` — sequence redesign on a fixed scaffold.
- `motif_scaffolding` — scaffold construction around a fixed motif.
- `hotspot_selection` — identify target hotspot residues.
