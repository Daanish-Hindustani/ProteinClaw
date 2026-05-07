# Skill Format

> Stub. Authored in Phase 3.

Skills are Markdown files under `src/proteinclaw/skills/protein_design/` with YAML front-matter:

```yaml
---
id: binder_design
name: Binder Design
version: 1
applicable_tasks: [binder_design]
provenance: human-authored | evolved
parent_version: null
---
```

Body is free-form Markdown describing the workflow with worked examples. The `SkillValidator` runs schema check + prompt-injection threat scan before any skill enters the library.

Edits use `SkillManager` actions: `create | edit | patch | delete`. `patch` (find-and-replace) is the default for evolution.
