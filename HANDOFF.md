# HANDOFF — Hermes integration rewrite (2026-06-24)

Branch: `feature/hermes_integration`. This file is the working handoff for the
in-flight task; durable lessons also went into `NOTES.md`. Delete this file once
the remaining tasks land and are folded into NOTES/docs.

## The task (owner request)
1. Verify the hermes-integration code is good.
2. Verify the workflow matches the architecture docs: research subagents that
   debate with the main agent, iteration, and leveraging Hermes self-evolution
   for skills.
3. Clean up code.
4. Documentation.
5. Make setup easy for the user.
6. Run a basic **generic protein binder** (not nanobody) end-to-end.

Owner decision (asked & answered): **rewrite the integration** to the real
hermes API (not verify-only).

## What was WRONG with the committed hermes integration (commit 30ca28b)
The refactor swapped the Claude Agent SDK for `hermes-agent` (`run_agent.AIAgent`),
but the harness was written against a **guessed** API and never actually drove the
model. Proven against the installed `run_agent` (5568-line single module):

- `hermes_harness._instantiate_agent` passed `tools=`, `toolsets=`, `cwd=` to
  `AIAgent(...)`. The real constructor accepts **none** of those → all explicit
  attempts `TypeError` → it fell through to `AIAgent(model=, ephemeral_system_prompt=)`,
  i.e. a **tools-less agent**. No RFD3/MPNN/ESMFold/AF2, no file tools, no scouts.
- It then called `run/query/ask/chat`; only `chat`/`run_conversation` exist, and the
  `callback=`/`on_event=` kwargs `TypeError` → bare `chat(prompt)` → **no trace events,
  empty final_text**.
- The 367 passing tests only passed because they injected a **mock `agent_cls`** — the
  real API was never exercised. "Tests green" was not evidence of a working integration.

## The REAL hermes API (verified, cite `.venv/.../{run_agent,model_tools,tools/registry}.py`)
- **Tool registration**: `model_tools.registry.register(name, toolset, schema, handler,
  is_async=, override=, description=, ...)`. Tools self-register; a custom toolset name
  is auto-recognized once any tool registers under it (no "create toolset" call).
- **Handler contract**: `handler(args: dict, **kwargs) -> str` (MUST return a JSON
  **string**). kwargs passed: `task_id, session_id, user_task`.
- **Schema shape**: OpenAI **inner** form `{"name","description","parameters":{<JSON Schema>}}`
  — the registry wraps it as `{"type":"function","function":{...}}` at emit time.
- **Exposure**: `get_tool_definitions(enabled_toolsets=[...])` surfaces a tool iff it's
  registered + its toolset name is in `enabled_toolsets`. `enabled_toolsets` are NAMES.
- **Construct**: `AIAgent(model=, ephemeral_system_prompt=, max_iterations=, session_id=,
  enabled_toolsets=, quiet_mode=, skip_context_files=, skip_memory=, <callbacks>)`. Sync
  constructor; **raises RuntimeError if no provider configured** (needs `OPENROUTER_API_KEY`
  or explicit base_url/api_key/provider, or `~/.hermes/config.yaml`).
- **Run**: `run_conversation(user_message, ...) -> dict` is the full autonomous multi-tool
  loop (sync). `chat()` wraps it and returns only `final_response`. Return-dict keys:
  `final_response`, `api_calls` (NOT num_turns), `estimated_cost_usd` (NOT cost),
  `completed`, `messages`, token counts, `session_id`.
- **Trace callbacks** (event_callback is a red herring — only fires `session:compress`):
  - `tool_start_callback(tool_call_id, name, args)`
  - `tool_complete_callback(tool_call_id, name, args, function_result:str)`
  - `interim_assistant_callback(visible_text, already_streamed)` — assistant text
  - `reasoning_callback(reasoning_text)` — model thinking (non-streaming)
  - `thinking_callback` is a spinner STATUS string, not reasoning — don't use for trace.
- **Native toolsets available** (no key for web via ddgs): `web` (web_search/web_extract),
  `skills` (**skill_manage / skill_view / skills_list** — this is hermes self-evo), `file`,
  `terminal`, `code_execution`, `memory`, `delegation`, etc. `get_hermes_home()` → `~/.hermes`.
- **Sub-agent pattern**: build a second `AIAgent` scoped to a read-only toolset and call
  `run_conversation` (mirror `tools/delegate_tool.py`; don't reach into the delegation
  machinery). Set `skip_context_files=True, skip_memory=True`.

## What I changed (DONE — all 374 host tests green, +7 net)
- **`src/proteinclaw/agent/mcp_tools.py`** — rewritten. `HermesToolSpec` now carries a
  `toolset` + `hermes_schema` (OpenAI inner shape). `proteinclaw_tool_specs(...)` builds
  specs; `register_specs(hermes_registry, specs)` registers them as **async, override=True**
  and returns toolset names. Domain tools split across two toolsets:
  `proteinclaw` (GPU/design/analysis — privileged) and `proteinclaw_research`
  (data/research retrieval — scout-safe, by category). Handler returns the envelope **dict**;
  `register_specs` JSON-stringifies it (triage already accepts a plain JSON string).
  Kept stable `mcp__proteinclaw_tools__<flat>` names + `_translate_host_path_to_workspace` +
  `_accepts_param`. Removed `build_hermes_toolset`/`build_mcp_server`/`allowed_tool_glob`'s
  old role (glob kept).
- **`src/proteinclaw/agent/hermes_builtins.py`** — rewritten. `build_builtin_specs(...)` →
  list[HermesToolSpec]. Reads (`file_read`/`file_search`) → research toolset (scouts can use);
  writes/`shell_exec`/`research_scout` → privileged toolset. **Dropped the web_* stubs**
  (hermes native `web` replaces them). file/shell tools kept on purpose: they run in the
  **host venv** (biopython structural sandbox needs that; hermes code tool is sandboxed).
- **`src/proteinclaw/agent/hermes_harness.py`** — rewritten to the real API. Registers specs
  into `model_tools.registry` (injectable), constructs `AIAgent` with the real kwargs +
  wires the 4 trace callbacks, drives via `asyncio.to_thread(agent.run_conversation, prompt)`
  (keeps the event loop + Ctrl-C handling in `_drive` alive), normalises the result dict
  (`final_response`→final_text, `api_calls`→num_turns, `estimated_cost_usd`→total_cost_usd).
- **`src/proteinclaw/agent/core.py`** — `_drive` now builds specs (domain + builtins),
  enables `[proteinclaw, proteinclaw_research, web, skills]`, scout reuses the already-
  registered `proteinclaw_research` toolset (`register=False`). `_build_options` takes
  `specs`/`enabled_toolsets` instead of `toolsets`. New consts `NATIVE_MAIN_TOOLSETS`/
  `NATIVE_SCOUT_TOOLSETS`. Scout docstring de-"Task"-ified.
- **Tests** — `tests/agent/test_mcp_tools.py` + `test_agents.py` rewritten to the new shapes,
  PLUS a **real integration test** (`test_real_hermes_registry_exposes_proteinclaw_tools`)
  that registers into the actual `model_tools.registry` and asserts `get_tool_definitions`
  surfaces our tools under the right toolset — the path that was silently broken. Harness
  test uses a `_FakeAIAgent` that fires the REAL callbacks + returns the REAL result keys.

## REMAINING WORK (tasks 5–7)
5. **Cleanup** (task #5): stale "SDK"/"Task tool" wording in `cli.py:131,161`, `triage.py:35-36`,
   `skills/proteindesign.md:129,154` (skill still says spawn via the `Task` tool — should be
   `research_scout`), comment in `trace.py:88`. Unused `tomllib` import in `doctor.py:28`.
   `doctor.py:11-12` docstring grammar. `cli.py:213` "skills evolved … file(s)" label now
   = hermes skill names.
6. **Docs + easy setup** (task #6): ARCHITECTURE.md/README.md/CLAUDE.md still describe the
   Claude Agent SDK + OAuth subscription billing. Now it's hermes + OpenRouter/provider keys.
   `doctor.check_hermes_auth` checks env keys / `~/.hermes` — note it looks for `config.toml`
   but hermes actually uses **`~/.hermes/config.yaml`** (+ `~/.hermes/.env`); also `get_hermes_home`
   honors `HERMES_HOME`. setup.py/doctor never verify `hermes-agent` is importable — add that.
   Document the workflow (research scouts → debate → iteration → skill_manage self-evo).
7. **Run a generic binder** (task #7): BLOCKED on provider creds. `AIAgent` construction
   RAISES without a provider. Need `OPENROUTER_API_KEY` (or anthropic via hermes config).
   The old NOTES auth entry (OAuth via `claude login`) is **obsolete** — that was the Claude
   Agent SDK. Then: doctor green → `proteinclaw run "<generic binder prompt>" --workflow minibinder`.
   First run triggers ~30-60 min cold Docker image builds (RFD3/MPNN/ESMFold/AF2) + weight pulls.

## Footguns discovered
- `register override=True` is deliberate: a fresh campaign rebinds session-scoped handler
  closures over any prior registration in the same process.
- Scout must use `register=False` (the research toolset is already registered by the main
  harness in the same process) or it double-registers.
- `model_tools.registry` registration is process-global; fine for one campaign per process
  (the CLI model), but tests that register must tolerate idempotent re-registration (override).
