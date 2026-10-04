"""Sandbox interface - the contract every execution backend honours."""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class SandboxSpec:
    """What to stand up before running a command."""
    image: str = "python:3.11-slim"
    gpu: bool = True
    node_id: Optional[str] = None          # fleet node this sandbox is pinned to
    env: Dict[str, str] = field(default_factory=dict)
    workdir: str = "/work"


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str = ""
    duration_s: float = 0.0
    artifacts: Dict[str, str] = field(default_factory=dict)  # path -> text content
    truncated: bool = False    # the backend cut stdout/stderr at its size limit

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class Sandbox(abc.ABC):
    """Create -> put files -> exec -> collect -> destroy."""

    mode: str = "abstract"

    @abc.abstractmethod
    def create(self, spec: SandboxSpec) -> str:
        """Provision an isolated environment. Returns a sandbox id."""

    @abc.abstractmethod
    def put_files(self, sandbox_id: str, files: Dict[str, str]) -> None:
        """Write ``{relpath: content}`` into the sandbox workdir."""

    @abc.abstractmethod
    def exec(self, sandbox_id: str, command: str, timeout: int = 120) -> ExecResult:
        """Run one shell command, capture output."""

    @abc.abstractmethod
    def collect(self, sandbox_id: str, paths: list) -> Dict[str, str]:
        """Read back ``paths`` from the sandbox workdir."""

    @abc.abstractmethod
    def destroy(self, sandbox_id: str) -> None:
        """Tear the environment down."""
