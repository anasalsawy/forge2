"""Workspace-bounded local tools with explicit exit codes and auditable results."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

MAX_OUTPUT = 50_000


def _inside(root: Path, value: str | Path) -> Path:
    candidate = (root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"path escapes workspace: {value}")
    return candidate


def _result(proc: subprocess.CompletedProcess[str]) -> str:
    body = {
        "exit_code": proc.returncode,
        "stdout": (proc.stdout or "")[:MAX_OUTPUT],
        "stderr": (proc.stderr or "")[:MAX_OUTPUT],
        "ok": proc.returncode == 0,
    }
    return json.dumps(body, ensure_ascii=False)


class ShellArgs(BaseModel):
    command: str = Field(description="Shell command to execute inside the configured workspace")
    cwd: str = "."
    timeout: int = Field(180, ge=1, le=1800)


class WorkspaceShellTool(BaseTool):
    name: str = "workspace_shell"
    description: str = "Run a shell command inside the project workspace and return explicit JSON with exit_code, stdout, stderr, and ok."
    args_schema: type[BaseModel] = ShellArgs
    workspace: Path

    def _run(self, command: str, cwd: str = ".", timeout: int = 180) -> str:
        run_dir = _inside(self.workspace, cwd)
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=run_dir,
                env=os.environ.copy(),
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            return _result(proc)
        except subprocess.TimeoutExpired as exc:
            return json.dumps({"ok": False, "exit_code": None, "error": "timeout", "stdout": exc.stdout or "", "stderr": exc.stderr or ""})


class ReadArgs(BaseModel):
    path: str
    max_chars: int = Field(50_000, ge=1, le=200_000)


class WorkspaceReadTool(BaseTool):
    name: str = "workspace_read"
    description: str = "Read a UTF-8 file inside the configured workspace."
    args_schema: type[BaseModel] = ReadArgs
    workspace: Path

    def _run(self, path: str, max_chars: int = 50_000) -> str:
        target = _inside(self.workspace, path)
        return target.read_text(encoding="utf-8")[:max_chars]


class WriteArgs(BaseModel):
    path: str
    content: str
    append: bool = False


class WorkspaceWriteTool(BaseTool):
    name: str = "workspace_write"
    description: str = "Write UTF-8 content to a path inside the configured workspace."
    args_schema: type[BaseModel] = WriteArgs
    workspace: Path

    def _run(self, path: str, content: str, append: bool = False) -> str:
        target = _inside(self.workspace, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with target.open(mode, encoding="utf-8", newline="\n") as handle:
            count = handle.write(content)
        return json.dumps({"ok": True, "path": str(target.relative_to(self.workspace)), "characters": count})


class ListArgs(BaseModel):
    path: str = "."


class WorkspaceListTool(BaseTool):
    name: str = "workspace_list"
    description: str = "Recursively list workspace files under a bounded path."
    args_schema: type[BaseModel] = ListArgs
    workspace: Path

    def _run(self, path: str = ".") -> str:
        root = _inside(self.workspace, path)
        files = sorted(str(p.relative_to(self.workspace)) for p in root.rglob("*") if p.is_file() and ".git" not in p.parts)
        return json.dumps({"ok": True, "files": files[:5000], "truncated": len(files) > 5000})


class GitArgs(BaseModel):
    arguments: str = Field(description="Git arguments without the leading git, with normal shell quoting")
    timeout: int = Field(120, ge=1, le=600)


class WorkspaceGitTool(BaseTool):
    name: str = "workspace_git"
    description: str = "Run git with shell-aware argument parsing in the workspace and return the exact exit code."
    args_schema: type[BaseModel] = GitArgs
    workspace: Path

    def _run(self, arguments: str, timeout: int = 120) -> str:
        args = shlex.split(arguments)
        if args and args[0] == "git":
            args = args[1:]
        if not args:
            return json.dumps({"ok": False, "error": "no git arguments"})
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=self.workspace,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            return _result(proc)
        except subprocess.TimeoutExpired:
            return json.dumps({"ok": False, "exit_code": None, "error": "timeout"})


class ValidationArgs(BaseModel):
    command: str = Field(description="Project-specific validation command")
    timeout: int = Field(600, ge=1, le=1800)


class ValidationTool(BaseTool):
    name: str = "validate_project"
    description: str = "Run a caller-selected validation command and decide PASS strictly from exit code zero."
    args_schema: type[BaseModel] = ValidationArgs
    workspace: Path

    def _run(self, command: str, timeout: int = 600) -> str:
        shell = WorkspaceShellTool(workspace=self.workspace)
        result = json.loads(shell._run(command=command, timeout=timeout))
        result["validation"] = "PASS" if result.get("exit_code") == 0 else "FAIL"
        return json.dumps(result, ensure_ascii=False)
