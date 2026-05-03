#!/usr/bin/env python3
"""
Toolsets Module — protein-design focused.

Defines and resolves named groups of tools. Trimmed from the full ProteinClaw
toolset catalog to the subset relevant to a protein-design agent: web research,
file/terminal/code, browser, planning/memory, code execution, delegation,
RL training scaffolding, and the protein_design plugin.

Usage:
    from toolsets import get_toolset, resolve_toolset, get_all_toolsets

    tools = get_toolset("protein_design")
    all_tools = resolve_toolset("debugging")
"""

from typing import List, Dict, Any, Set, Optional


# Shared tool list for the CLI runtime. Edit once to update CLI defaults.
_HERMES_CORE_TOOLS = [
    # Web
    "web_search", "web_extract",
    # Terminal + process management
    "terminal", "process",
    # File manipulation
    "read_file", "write_file", "patch", "search_files",
    # Skills
    "skills_list", "skill_view", "skill_manage",
    # Browser automation
    "browser_navigate", "browser_snapshot", "browser_click",
    "browser_type", "browser_scroll", "browser_back",
    "browser_press", "browser_get_images",
    "browser_vision", "browser_console", "browser_cdp", "browser_dialog",
    # Planning & memory
    "todo", "memory",
    # Session history search
    "session_search",
    # Clarifying questions
    "clarify",
    # Code execution + delegation
    "execute_code", "delegate_task",
    # Cronjob management
    "cronjob",
]


# Core toolset definitions.
TOOLSETS = {
    "web": {
        "description": "Web research and content extraction tools",
        "tools": ["web_search", "web_extract"],
        "includes": []
    },

    "search": {
        "description": "Web search only (no content extraction/scraping)",
        "tools": ["web_search"],
        "includes": []
    },

    "terminal": {
        "description": "Terminal/command execution and process management tools",
        "tools": ["terminal", "process"],
        "includes": []
    },

    "moa": {
        "description": "Advanced reasoning via mixture-of-agents",
        "tools": ["mixture_of_agents"],
        "includes": []
    },

    "skills": {
        "description": "Access, create, edit, and manage skill documents",
        "tools": ["skills_list", "skill_view", "skill_manage"],
        "includes": []
    },

    "browser": {
        "description": "Browser automation for web interaction with web search for finding URLs",
        "tools": [
            "browser_navigate", "browser_snapshot", "browser_click",
            "browser_type", "browser_scroll", "browser_back",
            "browser_press", "browser_get_images",
            "browser_vision", "browser_console", "browser_cdp",
            "browser_dialog", "web_search"
        ],
        "includes": []
    },

    "cronjob": {
        "description": "Cronjob management - create, list, update, pause, resume, remove, trigger scheduled tasks",
        "tools": ["cronjob"],
        "includes": []
    },

    "rl": {
        "description": "RL training tools for running reinforcement learning on Tinker-Atropos",
        "tools": [
            "rl_list_environments", "rl_select_environment",
            "rl_get_current_config", "rl_edit_config",
            "rl_start_training", "rl_check_status",
            "rl_stop_training", "rl_get_results",
            "rl_list_runs", "rl_test_inference"
        ],
        "includes": []
    },

    "protein_design": {
        "description": "Protein design tools: PubMed, UniProt, RCSB, RFdiffusion3, ProteinMPNN, ESMFold, AF2-Multimer",
        "tools": [
            "pubmed_search", "uniprot_search", "rcsb_search",
            "rfd3_design", "protein_mpnn_design", "esmfold_predict",
            "alphafold2_multimer_predict",
        ],
        "includes": []
    },

    "file": {
        "description": "File manipulation: read, write, patch (fuzzy match), search (content + files)",
        "tools": ["read_file", "write_file", "patch", "search_files"],
        "includes": []
    },

    "todo": {
        "description": "Task planning and tracking for multi-step work",
        "tools": ["todo"],
        "includes": []
    },

    "memory": {
        "description": "Persistent memory across sessions (personal notes + user profile)",
        "tools": ["memory"],
        "includes": []
    },

    "session_search": {
        "description": "Search and recall past conversations with summarization",
        "tools": ["session_search"],
        "includes": []
    },

    "clarify": {
        "description": "Ask the user clarifying questions (multiple-choice or open-ended)",
        "tools": ["clarify"],
        "includes": []
    },

    "code_execution": {
        "description": "Run Python scripts that call tools programmatically (reduces LLM round trips)",
        "tools": ["execute_code"],
        "includes": []
    },

    "delegation": {
        "description": "Spawn subagents with isolated context for complex subtasks",
        "tools": ["delegate_task"],
        "includes": []
    },

    "debugging": {
        "description": "Debugging and troubleshooting toolkit",
        "tools": ["terminal", "process"],
        "includes": ["web", "file"]
    },

    "safe": {
        "description": "Safe toolkit without terminal access (web research only)",
        "tools": [],
        "includes": ["web"]
    },

    # Runtime-specific bundles
    "hermes-acp": {
        "description": "Editor integration (VS Code, Zed, JetBrains) — coding-focused tools without messaging or clarify UI",
        "tools": [
            "web_search", "web_extract",
            "terminal", "process",
            "read_file", "write_file", "patch", "search_files",
            "skills_list", "skill_view", "skill_manage",
            "browser_navigate", "browser_snapshot", "browser_click",
            "browser_type", "browser_scroll", "browser_back",
            "browser_press", "browser_get_images",
            "browser_vision", "browser_console", "browser_cdp", "browser_dialog",
            "todo", "memory",
            "session_search",
            "execute_code", "delegate_task",
        ],
        "includes": []
    },

    "hermes-api-server": {
        "description": "OpenAI-compatible API server — full agent tools accessible via HTTP (no interactive UI tools)",
        "tools": [
            "web_search", "web_extract",
            "terminal", "process",
            "read_file", "write_file", "patch", "search_files",
            "skills_list", "skill_view", "skill_manage",
            "browser_navigate", "browser_snapshot", "browser_click",
            "browser_type", "browser_scroll", "browser_back",
            "browser_press", "browser_get_images",
            "browser_vision", "browser_console", "browser_cdp", "browser_dialog",
            "todo", "memory",
            "session_search",
            "execute_code", "delegate_task",
            "cronjob",
        ],
        "includes": []
    },

    "hermes-cli": {
        "description": "Full interactive CLI toolset",
        "tools": _HERMES_CORE_TOOLS,
        "includes": []
    },

    "hermes-cron": {
        "description": "Default cron toolset - same core tools as hermes-cli; gated by `hermes tools`",
        "tools": _HERMES_CORE_TOOLS,
        "includes": []
    },
}


def get_toolset(name: str) -> Optional[Dict[str, Any]]:
    """Get a toolset definition by name (with plugin-registered fallback)."""
    toolset = TOOLSETS.get(name)
    if toolset:
        return toolset

    try:
        from tools.registry import registry
    except Exception:
        return None

    registry_toolset = name
    description = f"Plugin toolset: {name}"
    alias_target = registry.get_toolset_alias_target(name)

    if name not in _get_plugin_toolset_names():
        registry_toolset = alias_target
        if not registry_toolset:
            return None
        description = f"MCP server '{name}' tools"
    else:
        reverse_aliases = {
            canonical: alias
            for alias, canonical in _get_registry_toolset_aliases().items()
            if alias not in TOOLSETS
        }
        alias = reverse_aliases.get(name)
        if alias:
            description = f"MCP server '{alias}' tools"

    return {
        "description": description,
        "tools": registry.get_tool_names_for_toolset(registry_toolset),
        "includes": [],
    }


def resolve_toolset(name: str, visited: Set[str] = None) -> List[str]:
    """Recursively resolve a toolset to all tool names."""
    if visited is None:
        visited = set()

    if name in {"all", "*"}:
        all_tools: Set[str] = set()
        for toolset_name in get_toolset_names():
            resolved = resolve_toolset(toolset_name, visited.copy())
            all_tools.update(resolved)
        return sorted(all_tools)

    if name in visited:
        return []

    visited.add(name)

    toolset = get_toolset(name)
    if not toolset:
        return []

    tools = set(toolset.get("tools", []))

    for included_name in toolset.get("includes", []):
        included_tools = resolve_toolset(included_name, visited)
        tools.update(included_tools)

    return sorted(tools)


def resolve_multiple_toolsets(toolset_names: List[str]) -> List[str]:
    """Resolve multiple toolsets and combine, deduplicated."""
    all_tools = set()
    for name in toolset_names:
        all_tools.update(resolve_toolset(name))
    return sorted(all_tools)


def _get_plugin_toolset_names() -> Set[str]:
    """Toolset names registered by plugins (in registry but not in static TOOLSETS)."""
    try:
        from tools.registry import registry
        return {
            toolset_name
            for toolset_name in registry.get_registered_toolset_names()
            if toolset_name not in TOOLSETS
        }
    except Exception:
        return set()


def _get_registry_toolset_aliases() -> Dict[str, str]:
    """Explicit toolset aliases registered in the live registry."""
    try:
        from tools.registry import registry
        return registry.get_registered_toolset_aliases()
    except Exception:
        return {}


def get_all_toolsets() -> Dict[str, Dict[str, Any]]:
    """All toolset definitions (static + plugin-registered)."""
    result = dict(TOOLSETS)
    aliases = _get_registry_toolset_aliases()
    for ts_name in _get_plugin_toolset_names():
        display_name = ts_name
        for alias, canonical in aliases.items():
            if canonical == ts_name and alias not in TOOLSETS:
                display_name = alias
                break
        if display_name in result:
            continue
        toolset = get_toolset(display_name)
        if toolset:
            result[display_name] = toolset
    return result


def get_toolset_names() -> List[str]:
    """Names of all available toolsets (excluding aliases)."""
    names = set(TOOLSETS.keys())
    aliases = _get_registry_toolset_aliases()
    for ts_name in _get_plugin_toolset_names():
        for alias, canonical in aliases.items():
            if canonical == ts_name and alias not in TOOLSETS:
                names.add(alias)
                break
        else:
            names.add(ts_name)
    return sorted(names)


def validate_toolset(name: str) -> bool:
    """True if toolset name is valid."""
    if name in {"all", "*"}:
        return True
    if name in TOOLSETS:
        return True
    if name in _get_plugin_toolset_names():
        return True
    return name in _get_registry_toolset_aliases()


def create_custom_toolset(
    name: str,
    description: str,
    tools: List[str] = None,
    includes: List[str] = None
) -> None:
    """Create a custom toolset at runtime."""
    TOOLSETS[name] = {
        "description": description,
        "tools": tools or [],
        "includes": includes or []
    }


def get_toolset_info(name: str) -> Dict[str, Any]:
    """Detailed info about a toolset including resolved tools."""
    toolset = get_toolset(name)
    if not toolset:
        return None

    resolved_tools = resolve_toolset(name)

    return {
        "name": name,
        "description": toolset["description"],
        "direct_tools": toolset["tools"],
        "includes": toolset["includes"],
        "resolved_tools": resolved_tools,
        "tool_count": len(resolved_tools),
        "is_composite": bool(toolset["includes"])
    }


if __name__ == "__main__":
    print("Toolsets System Demo")
    print("=" * 60)

    print("\nAvailable Toolsets:")
    print("-" * 40)
    for name, toolset in get_all_toolsets().items():
        info = get_toolset_info(name)
        composite = "[composite]" if info["is_composite"] else "[leaf]"
        print(f"  {composite} {name:20} - {toolset['description']}")
        print(f"     Tools: {len(info['resolved_tools'])} total")

    print("\nToolset Resolution Examples:")
    print("-" * 40)
    for name in ["web", "terminal", "safe", "debugging", "protein_design"]:
        tools = resolve_toolset(name)
        print(f"\n  {name}:")
        print(f"    Resolved to {len(tools)} tools: {', '.join(sorted(tools))}")
