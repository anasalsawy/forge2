"""CrewAI execution adapter. Orchestration logic is kept outside model prompts."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from crewai import LLM, Agent, Crew, Process, Task
from crewai_tools import FirecrawlScrapeWebsiteTool, FirecrawlSearchTool, ScrapeWebsiteTool

from .prompts import (
    AUDITOR_ROLE,
    BUILD_ANALYST_BACKSTORY,
    BUILD_ANALYST_GOAL,
    BUILD_ANALYST_ROLE,
    BUILDER_BACKSTORY,
    BUILDER_GOAL,
    BUILDER_ROLE,
    COMPILER_ROLE,
    RESEARCH_ANALYST_BACKSTORY,
    RESEARCH_ANALYST_GOAL,
    RESEARCH_ANALYST_ROLE,
    RESEARCH_WORKER_BACKSTORY,
    RESEARCH_WORKER_GOAL,
    RESEARCH_WORKER_ROLE,
)
from .settings import ModelConnection, Settings
from .tools import (
    GitHubTool,
    ValidationTool,
    WorkspaceGitTool,
    WorkspaceListTool,
    WorkspaceReadTool,
    WorkspaceShellTool,
    WorkspaceWriteTool,
)


class Runner(Protocol):
    def research_worker(self, task: str) -> str: ...
    def research_analyst(self, task: str) -> str: ...
    def compiler(self, task: str) -> str: ...
    def builder(self, task: str) -> str: ...
    def build_analyst(self, task: str) -> str: ...
    def auditor(self, task: str) -> str: ...


def _raw(output: object) -> str:
    value = getattr(output, "raw", output)
    text = str(value or "").strip()
    if not text:
        raise RuntimeError("model returned an empty output")
    return text


@dataclass
class CrewAIRunner:
    settings: Settings

    def __post_init__(self) -> None:
        self.settings.validate_connections()
        self.settings.workspace.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _llm(connection: ModelConnection) -> LLM:
        return LLM(model=connection.model, base_url=connection.base_url, api_key=connection.api_key)

    def _run(self, *, role: str, goal: str, backstory: str, task: str, expected: str,
             connection: ModelConnection, max_iter: int, tools: list | None = None) -> str:
        agent = Agent(
            role=role,
            goal=goal,
            backstory=backstory,
            llm=self._llm(connection),
            tools=tools or [],
            max_iter=max_iter,
            verbose=self.settings.verbose,
            allow_delegation=False,
            inject_date=True,
        )
        crew_task = Task(description=task, expected_output=expected, agent=agent)
        crew = Crew(agents=[agent], tasks=[crew_task], process=Process.sequential, verbose=self.settings.verbose)
        return _raw(crew.kickoff())

    def _research_tools(self) -> list:
        tools = [
            WorkspaceReadTool(workspace=self.settings.workspace),
            WorkspaceListTool(workspace=self.settings.workspace),
            ScrapeWebsiteTool(),
        ]
        if self.settings.github_repository:
            tools.append(GitHubTool(repository=self.settings.github_repository, read_only=True))
        if os.getenv("FIRECRAWL_API_KEY"):
            tools.extend([FirecrawlSearchTool(), FirecrawlScrapeWebsiteTool()])
        return tools

    def _build_tools(self, *, write: bool) -> list:
        tools = [
            WorkspaceReadTool(workspace=self.settings.workspace),
            WorkspaceListTool(workspace=self.settings.workspace),
            WorkspaceShellTool(workspace=self.settings.workspace),
            WorkspaceGitTool(workspace=self.settings.workspace),
            ValidationTool(workspace=self.settings.workspace),
        ]
        if write:
            tools.append(WorkspaceWriteTool(workspace=self.settings.workspace))
            if self.settings.github_repository:
                tools.append(GitHubTool(repository=self.settings.github_repository))
        return tools

    def research_worker(self, task: str) -> str:
        return self._run(role=RESEARCH_WORKER_ROLE, goal=RESEARCH_WORKER_GOAL,
                         backstory=RESEARCH_WORKER_BACKSTORY, task=task,
                         expected="Complete cumulative investigation with evidence and source inventory.",
                         connection=self.settings.worker, max_iter=self.settings.worker_max_iter,
                         tools=self._research_tools())

    def research_analyst(self, task: str) -> str:
        return self._run(role=RESEARCH_ANALYST_ROLE, goal=RESEARCH_ANALYST_GOAL,
                         backstory=RESEARCH_ANALYST_BACKSTORY, task=task,
                         expected="Evidence review ending in one exact VERDICT line.",
                         connection=self.settings.reviewer, max_iter=self.settings.reviewer_max_iter,
                         tools=self._research_tools())

    def compiler(self, task: str) -> str:
        return self._run(role=COMPILER_ROLE, goal="Compile the complete accepted research record without information loss.",
                         backstory="You preserve evidence, provenance, contradictions, and uncertainty.", task=task,
                         expected="Definitive Research Master Record.", connection=self.settings.compiler,
                         max_iter=self.settings.compiler_max_iter, tools=self._research_tools())

    def builder(self, task: str) -> str:
        return self._run(role=BUILDER_ROLE, goal=BUILDER_GOAL, backstory=BUILDER_BACKSTORY,
                         task=task, expected="Complete cumulative implementation handoff with real validation evidence.",
                         connection=self.settings.worker, max_iter=self.settings.worker_max_iter,
                         tools=self._build_tools(write=True))

    def build_analyst(self, task: str) -> str:
        return self._run(role=BUILD_ANALYST_ROLE, goal=BUILD_ANALYST_GOAL,
                         backstory=BUILD_ANALYST_BACKSTORY, task=task,
                         expected="Independent workspace review ending in one exact VERDICT line.",
                         connection=self.settings.reviewer, max_iter=self.settings.reviewer_max_iter,
                         tools=self._build_tools(write=False))

    def auditor(self, task: str) -> str:
        return self._run(role=AUDITOR_ROLE, goal="Release only a complete, verified implementation.",
                         backstory="You are the final independent evidence gate and never infer success from execution count.",
                         task=task, expected="Full audit ending in one exact FINAL_VERDICT line.",
                         connection=self.settings.auditor, max_iter=self.settings.auditor_max_iter,
                         tools=self._build_tools(write=False))
