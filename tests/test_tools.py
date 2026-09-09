import json
import subprocess

import pytest

from forge2.tools.github import GitHubTool
from forge2.tools.local import (
    ValidationTool,
    WorkspaceGitTool,
    WorkspaceReadTool,
    WorkspaceShellTool,
    WorkspaceWriteTool,
)


def test_workspace_tools_block_escape(tmp_path):
    tool = WorkspaceReadTool(workspace=tmp_path)
    with pytest.raises(ValueError):
        tool._run("../secret")


def test_shell_and_validation_use_exit_code(tmp_path):
    shell = WorkspaceShellTool(workspace=tmp_path)
    failed = json.loads(shell._run("printf normal-output; exit 7"))
    assert failed["ok"] is False and failed["exit_code"] == 7
    validation = json.loads(ValidationTool(workspace=tmp_path)._run("printf no-failure-word; exit 3"))
    assert validation["validation"] == "FAIL"


def test_write_is_bounded(tmp_path):
    writer = WorkspaceWriteTool(workspace=tmp_path)
    assert json.loads(writer._run("a/b.txt", "hello"))["ok"] is True
    assert (tmp_path / "a/b.txt").read_text() == "hello"


def test_git_uses_shell_aware_parsing(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    result = json.loads(WorkspaceGitTool(workspace=tmp_path)._run('config user.name "Forge Two"'))
    assert result["ok"] is True
    name = subprocess.run(["git", "config", "user.name"], cwd=tmp_path, text=True, capture_output=True, check=True)
    assert name.stdout.strip() == "Forge Two"


def test_github_tool_accepts_crewai_keyword_shape(monkeypatch):
    tool = GitHubTool(repository="owner/repo")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    result = json.loads(tool._run(action="get", path="README.md"))
    assert result["ok"] is False
    assert "GITHUB_TOKEN" in result["error"]


def test_github_read_only_tool_rejects_mutation(monkeypatch):
    tool = GitHubTool(repository="owner/repo", read_only=True)
    monkeypatch.setenv("GITHUB_TOKEN", "unused")
    result = json.loads(tool._run(action="delete", path="README.md"))
    assert result == {"ok": False, "error": "this GitHub tool is read-only"}
