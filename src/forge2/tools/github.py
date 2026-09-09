"""A CrewAI-compatible GitHub contents tool with a configurable target repository."""

from __future__ import annotations

import base64
import json
import os

import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class GitHubArgs(BaseModel):
    action: str = Field(description="One of: get, list, create, update, delete")
    path: str = ""
    content: str = ""
    message: str = "Forge2 change"
    branch: str = ""
    sha: str = ""


class GitHubTool(BaseTool):
    name: str = "github_repository"
    description: str = "Read and modify files in the single GitHub repository configured by FORGE_GITHUB_REPOSITORY."
    args_schema: type[BaseModel] = GitHubArgs
    repository: str
    read_only: bool = False

    def _request(self, method: str, url: str, **kwargs) -> dict:
        token = os.getenv("GITHUB_TOKEN", "")
        if not token:
            raise RuntimeError("GITHUB_TOKEN is not configured")
        response = requests.request(
            method,
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
            timeout=30,
            **kwargs,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"GitHub returned {response.status_code}: {response.text[:500]}")
        return response.json() if response.content else {"status": response.status_code}

    def _run(self, action: str, path: str = "", content: str = "", message: str = "Forge2 change", branch: str = "", sha: str = "") -> str:
        if not self.repository or "/" not in self.repository:
            return json.dumps({"ok": False, "error": "FORGE_GITHUB_REPOSITORY must be owner/name"})
        try:
            if self.read_only and action not in {"get", "list"}:
                raise ValueError("this GitHub tool is read-only")
            repo_url = f"https://api.github.com/repos/{self.repository}"
            metadata = self._request("GET", repo_url)
            target_branch = branch or metadata["default_branch"]
            url = f"{repo_url}/contents/{path}"
            if action == "get" or action == "list":
                result = self._request("GET", url, params={"ref": target_branch})
            elif action in {"create", "update"}:
                payload = {"message": message, "content": base64.b64encode(content.encode()).decode(), "branch": target_branch}
                if action == "update":
                    current_sha = sha or self._request("GET", url, params={"ref": target_branch})["sha"]
                    payload["sha"] = current_sha
                result = self._request("PUT", url, json=payload)
            elif action == "delete":
                current_sha = sha or self._request("GET", url, params={"ref": target_branch})["sha"]
                result = self._request("DELETE", url, json={"message": message, "sha": current_sha, "branch": target_branch})
            else:
                raise ValueError("unknown action")
            return json.dumps({"ok": True, "result": result}, ensure_ascii=False)
        except (KeyError, RuntimeError, ValueError, requests.RequestException) as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
