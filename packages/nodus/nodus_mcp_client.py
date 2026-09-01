#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - NODUS MCP CLIENT
⚡ Registre multi-serveurs MCP : namespacing anti-shadow, pin anti-rug-pull,
   scan anti-poisoning sur les descriptions d'outils.
🔥 P3 : brancher de VRAIS serveurs MCP (stdio, SDK mcp 1.x).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import contextlib
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple, Union

import mcp.types as mcp_types
from mcp.client.session_group import ClientSessionGroup
from mcp.client.stdio import StdioServerParameters

_POISON_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"ignore\s+the\s+law",
        r"<\s*hidden\s*>",
        r"you\s+MUST\s+exfiltrate",
        r"developer\s+mode",
    )
)

ComponentNameHook = Callable[[str, mcp_types.Implementation], str]


def default_name_hook(name: str, server_info: mcp_types.Implementation) -> str:
    """Namespacing : server.tool — empêche le shadowing silencieux."""
    server = (server_info.name or "server").strip().replace(" ", "_")
    return f"{server}.{name}"


def schema_hash(tool: mcp_types.Tool) -> str:
    payload = {
        "name": tool.name,
        "description": tool.description or "",
        "inputSchema": tool.inputSchema or {},
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()[:16]


def scan_description_poisoning(description: str) -> Optional[str]:
    if not description:
        return None
    for rx in _POISON_PATTERNS:
        if rx.search(description):
            return rx.pattern
    return None


@dataclass
class McpToolEntry:
    qualified_name: str
    server_name: str
    bare_name: str
    description: str
    input_schema: dict
    schema_hash: str
    poison_pattern: Optional[str] = None


@dataclass
class McpToolRegistry:
    name_hook: ComponentNameHook = default_name_hook
    entries: Dict[str, McpToolEntry] = field(default_factory=dict)
    pinned_hashes: Dict[Tuple[str, str], str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def register_tool(
        self,
        qualified_name: str,
        server_name: str,
        tool: mcp_types.Tool,
        *,
        pin: bool = True,
    ) -> None:
        if qualified_name in self.entries:
            raise ValueError(
                f"tool shadowing: {qualified_name} already from "
                f"{self.entries[qualified_name].server_name}"
            )
        h = schema_hash(tool)
        key = (server_name, tool.name)
        if pin:
            if key in self.pinned_hashes and self.pinned_hashes[key] != h:
                self.warnings.append(
                    f"rug-pull: {server_name}.{tool.name} "
                    f"{self.pinned_hashes[key]} -> {h}"
                )
            self.pinned_hashes[key] = h
        poison = scan_description_poisoning(tool.description or "")
        self.entries[qualified_name] = McpToolEntry(
            qualified_name=qualified_name,
            server_name=server_name,
            bare_name=tool.name,
            description=tool.description or "",
            input_schema=dict(tool.inputSchema or {}),
            schema_hash=h,
            poison_pattern=poison,
        )
        if poison:
            self.warnings.append(f"poisoned-description: {qualified_name} /{poison}/")

    def ingest_session_group(self, group: ClientSessionGroup, *, pin: bool = True) -> None:
        """Remplit le registre depuis un ClientSessionGroup déjà connecté."""
        for qname, tool in group.tools.items():
            server_name = qname.rsplit(".", 1)[0] if "." in qname else "server"
            self.register_tool(qname, server_name, tool, pin=pin)

    def simulate_rug_pull(self, server_name: str, bare_name: str, new_description: str) -> bool:
        """Simule un changement de description post-approbation. Retourne True si détecté."""
        key = (server_name, bare_name)
        if key not in self.pinned_hashes:
            return False
        fake = mcp_types.Tool(
            name=bare_name,
            description=new_description,
            inputSchema={"type": "object", "properties": {}},
        )
        return self.pinned_hashes[key] != schema_hash(fake)

    def poisoned_tools(self) -> List[McpToolEntry]:
        return [e for e in self.entries.values() if e.poison_pattern]

    def bare_name_collisions(self) -> List[str]:
        by_bare: Dict[str, List[str]] = {}
        for e in self.entries.values():
            by_bare.setdefault(e.bare_name, []).append(e.server_name)
        return [n for n, srvs in by_bare.items() if len(srvs) > 1]


def stdio_params_for_script(script_name: str) -> StdioServerParameters:
    script = Path(__file__).parent.resolve() / "mcp_servers" / script_name
    if not script.exists():
        raise FileNotFoundError(script)
    return StdioServerParameters(command="python", args=[str(script)], env=None)


@asynccontextmanager
async def redteam_mcp_session(
    *,
    pin: bool = True,
) -> AsyncIterator[Tuple[McpToolRegistry, ClientSessionGroup]]:
    """Connecte trusted + evil (stdio) via ClientSessionGroup namespacé."""
    async with ClientSessionGroup(component_name_hook=default_name_hook) as group:
        for script in ("redteam_trusted.py", "redteam_evil.py"):
            await group.connect_to_server(stdio_params_for_script(script))
        registry = McpToolRegistry()
        registry.ingest_session_group(group, pin=pin)
        yield registry, group


# ── Config Cursor / Claude Desktop (.cursor/mcp.json) ─────────────────────────

def load_mcp_servers_config(path: Union[str, Path]) -> Dict[str, dict]:
    """Charge mcpServers depuis un fichier JSON style Cursor."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    servers = data.get("mcpServers") or data.get("servers") or {}
    if not isinstance(servers, dict):
        raise ValueError(f"invalid MCP config (no mcpServers): {path}")
    return servers


def find_mcp_config(
    explicit: Optional[str] = None,
    cwd: Optional[str] = None,
) -> Optional[Path]:
    """Cherche .cursor/mcp.json (explicit > cwd > process cwd > ~/.cursor)."""
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_file() else None
    candidates: List[Path] = []
    if cwd:
        candidates.append(Path(cwd) / ".cursor" / "mcp.json")
    candidates.append(Path.cwd() / ".cursor" / "mcp.json")
    candidates.append(Path.home() / ".cursor" / "mcp.json")
    seen: set = set()
    for candidate in candidates:
        try:
            key = candidate.resolve()
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return candidate
    return None


def parse_mcp_server_names(spec: str, config_path: Union[str, Path]) -> Tuple[str, ...]:
    """Parse 'godot', 'godot,cheatengine', ou 'all' depuis mcp.json."""
    servers = load_mcp_servers_config(config_path)
    raw = (spec or "").strip()
    if not raw:
        raise ValueError("empty mcp server spec")
    if raw.lower() == "all":
        return tuple(servers.keys())
    names = tuple(n.strip() for n in raw.split(",") if n.strip())
    missing = [n for n in names if n not in servers]
    if missing:
        raise ValueError(
            f"unknown mcp servers {missing}; available: {', '.join(sorted(servers))}"
        )
    return names


def stdio_params_from_entry(entry: dict) -> StdioServerParameters:
    """Convertit une entrée mcpServers en StdioServerParameters."""
    command = entry.get("command")
    if not command:
        raise ValueError("MCP server entry missing 'command'")
    args = list(entry.get("args") or [])
    env = entry.get("env")
    return StdioServerParameters(command=str(command), args=args, env=env)


def mcp_entry_to_schema(entry: McpToolEntry) -> dict:
    """Convertit un outil MCP en schéma OpenAI-compatible pour Ollama."""
    return {
        "type": "function",
        "function": {
            "name": entry.qualified_name,
            "description": entry.description or f"MCP tool {entry.qualified_name}",
            "parameters": entry.input_schema or {"type": "object", "properties": {}},
        },
    }


def registry_to_schemas(
    registry: McpToolRegistry,
    *,
    exclude_poisoned: bool = True,
) -> List[dict]:
    """Liste de schémas pour le LLM (optionnellement sans outils empoisonnés)."""
    out: List[dict] = []
    for entry in registry.entries.values():
        if exclude_poisoned and entry.poison_pattern:
            continue
        out.append(mcp_entry_to_schema(entry))
    return out


# Chemins raccourcis souvent hallucinés par les LLM (--text-tools).
_GODOT_SCENE_PATH_ALIASES = {
    "res://Main.tscn": "res://scenes/Main.tscn",
    "res://main.tscn": "res://scenes/Main.tscn",
}


def normalize_mcp_tool_arguments(qualified_name: str, arguments: Optional[dict]) -> dict:
    """Normalise les args MCP (alias params Godot mal nommés par le LLM)."""
    args = dict(arguments or {})
    bare = qualified_name.rsplit(".", 1)[-1]
    if bare == "run_scene" and "scene_path" in args and "scene" not in args:
        args["scene"] = args.pop("scene_path")
    if bare == "send_input" and "event" not in args:
        action = args.pop("action", None)
        if isinstance(action, str):
            evt: dict = {"type": "action", "action": action}
            if "pressed" in args:
                evt["pressed"] = args.pop("pressed")
            if "strength" in args:
                evt["strength"] = args.pop("strength")
            args["event"] = evt
    for key in ("scene", "scene_path", "path"):
        val = args.get(key)
        if isinstance(val, str) and val.strip().startswith("res://"):
            args[key] = _GODOT_SCENE_PATH_ALIASES.get(val.strip(), val)
    if bare in ("persistent_scan_first_scan", "persistent_scan_next_scan"):
        val = args.get("value")
        if val is not None and isinstance(val, (int, float)) and not isinstance(val, bool):
            args["value"] = str(int(val) if isinstance(val, float) and val.is_integer() else val)
    return args


async def mcp_call_to_tool_result(
    group: ClientSessionGroup,
    name: str,
    arguments: Optional[dict],
) -> "ToolResult":
    """Exécute un outil MCP et renvoie un ToolResult nodus_tools."""
    from nodus_tools import ToolResult  # import tardif — évite cycle au chargement

    try:
        norm_args = normalize_mcp_tool_arguments(name, arguments)
        result = await group.call_tool(name, norm_args)
        chunks: List[str] = []
        for block in result.content or []:
            text = getattr(block, "text", None)
            if text:
                chunks.append(text)
        output = "\n".join(chunks)
        if getattr(result, "isError", False):
            return ToolResult(success=False, output="", error=output or "MCP tool error")
        return ToolResult(success=True, output=output or "(no output)")
    except Exception as exc:
        return ToolResult(success=False, output="", error=f"MCP error: {exc}")


class McpBridge:
    """Pont sync MCP → nodus_agent (boucle asyncio dédiée par session)."""

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stack: Optional[contextlib.AsyncExitStack] = None
        self._group: Optional[ClientSessionGroup] = None
        self.registry: Optional[McpToolRegistry] = None
        self.config_path: Optional[Path] = None
        self.server_names: Tuple[str, ...] = ()

    def connect_servers(
        self,
        config_path: Union[str, Path],
        server_names: Tuple[str, ...],
    ) -> Optional[str]:
        """Connecte les serveurs nommés. Retourne un message d'erreur ou None."""
        self.config_path = Path(config_path)
        self.server_names = server_names
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stack = contextlib.AsyncExitStack()
        try:
            self._loop.run_until_complete(self._stack.__aenter__())
            err = self._loop.run_until_complete(
                self._async_connect(self.config_path, server_names)
            )
            return err
        except Exception as exc:
            self.close()
            return f"MCP connect failed: {exc}"

    def connect_godot(
        self,
        config_path: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> Optional[str]:
        """Connecte le serveur 'godot' depuis .cursor/mcp.json."""
        path = find_mcp_config(config_path, cwd)
        if path is None:
            return (
                "Godot MCP config not found. Expected .cursor/mcp.json "
                f"(cwd={cwd or Path.cwd()}). Use --mcp-config PATH."
            )
        servers = load_mcp_servers_config(path)
        if "godot" not in servers:
            return f"'godot' missing in mcpServers ({path})"
        return self.connect_servers(path, ("godot",))

    def connect_mcp(
        self,
        server_spec: str,
        config_path: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> Optional[str]:
        """Connecte un ou plusieurs serveurs nommés dans mcp.json ('all' ok)."""
        path = find_mcp_config(config_path, cwd)
        if path is None:
            return (
                "MCP config not found. Expected .cursor/mcp.json "
                f"(cwd={cwd or Path.cwd()} or ~/.cursor). Use --mcp-config PATH."
            )
        try:
            names = parse_mcp_server_names(server_spec, path)
        except ValueError as exc:
            return str(exc)
        return self.connect_servers(path, names)

    async def _async_connect(
        self,
        config_path: Path,
        server_names: Tuple[str, ...],
    ) -> Optional[str]:
        servers = load_mcp_servers_config(config_path)
        missing = [n for n in server_names if n not in servers]
        if missing:
            return f"MCP servers not in config: {', '.join(missing)}"

        self._group = await self._stack.enter_async_context(
            ClientSessionGroup(component_name_hook=default_name_hook)
        )
        try:
            for name in server_names:
                params = stdio_params_from_entry(servers[name])
                await self._group.connect_to_server(params)
        except Exception:
            await self._stack.aclose()
            self._stack = None
            self._group = None
            raise

        self.registry = McpToolRegistry()
        self.registry.ingest_session_group(self._group, pin=True)
        return None

    def has_tool(self, qualified_name: str) -> bool:
        return bool(self.registry and qualified_name in self.registry.entries)

    def schemas(self, *, exclude_poisoned: bool = True) -> List[dict]:
        if not self.registry:
            return []
        return registry_to_schemas(self.registry, exclude_poisoned=exclude_poisoned)

    def tool_names_summary(self, limit: int = 12) -> str:
        if not self.registry:
            return ""
        names = sorted(self.registry.entries.keys())
        preview = ", ".join(names[:limit])
        extra = f" (+{len(names) - limit} more)" if len(names) > limit else ""
        return preview + extra

    def call(self, qualified_name: str, arguments: Optional[dict]) -> Any:
        if not self._loop or not self._group:
            from nodus_tools import ToolResult
            return ToolResult(success=False, output="", error="MCP bridge not connected")
        return self._loop.run_until_complete(
            mcp_call_to_tool_result(self._group, qualified_name, arguments)
        )

    def close(self) -> None:
        if self._loop and self._stack:
            try:
                self._loop.run_until_complete(
                    self._stack.aclose()
                )
            except RuntimeError:
                # Teardown stdio MCP (anyio cancel scopes) peut grincer sur Windows.
                pass
            finally:
                try:
                    self._loop.close()
                except Exception:
                    pass
        self._loop = None
        self._stack = None
        self._group = None
        self.registry = None
