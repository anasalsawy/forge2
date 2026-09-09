"""Environment-backed runtime settings with early validation."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelConnection(BaseModel):
    model: str
    base_url: str
    api_key: str

    def require_ready(self, label: str) -> ModelConnection:
        missing = [name for name in ("model", "base_url", "api_key") if not getattr(self, name)]
        if missing:
            raise ValueError(f"{label} model connection is missing: {', '.join(missing)}")
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env",), extra="ignore")

    worker_model: str = Field("openai/gemini-3.5-flash-lite", alias="FORGE_WORKER_MODEL")
    worker_base_url: str = Field("https://generativelanguage.googleapis.com/v1beta/openai", alias="FORGE_WORKER_BASE_URL")
    worker_api_key: str = Field("", alias="FORGE_WORKER_API_KEY")
    reviewer_model: str = Field("openai/zai-org/GLM-5.3-Flash", alias="FORGE_REVIEWER_MODEL")
    reviewer_base_url: str = Field("https://api.featherless.ai/v1", alias="FORGE_REVIEWER_BASE_URL")
    reviewer_api_key: str = Field("", alias="FORGE_REVIEWER_API_KEY")
    compiler_model: str = Field("", alias="FORGE_COMPILER_MODEL")
    compiler_base_url: str = Field("", alias="FORGE_COMPILER_BASE_URL")
    compiler_api_key: str = Field("", alias="FORGE_COMPILER_API_KEY")
    auditor_model: str = Field("", alias="FORGE_AUDITOR_MODEL")
    auditor_base_url: str = Field("", alias="FORGE_AUDITOR_BASE_URL")
    auditor_api_key: str = Field("", alias="FORGE_AUDITOR_API_KEY")

    research_floors: int = Field(6, ge=1, le=12, alias="FORGE_RESEARCH_FLOORS")
    build_floors: int = Field(6, ge=1, le=12, alias="FORGE_BUILD_FLOORS")
    max_corrections: int = Field(3, ge=1, le=10, alias="FORGE_MAX_CORRECTIONS")
    allow_pass_with_notes: bool = Field(False, alias="FORGE_ALLOW_PASS_WITH_NOTES")
    worker_max_iter: int = Field(25, ge=1, alias="FORGE_WORKER_MAX_ITER")
    reviewer_max_iter: int = Field(12, ge=1, alias="FORGE_REVIEWER_MAX_ITER")
    compiler_max_iter: int = Field(12, ge=1, alias="FORGE_COMPILER_MAX_ITER")
    auditor_max_iter: int = Field(15, ge=1, alias="FORGE_AUDITOR_MAX_ITER")
    workspace: Path = Field(Path("workspace"), alias="FORGE_WORKSPACE")
    state_dir: Path = Field(Path(".forge2"), alias="FORGE_STATE_DIR")
    verbose: bool = Field(True, alias="FORGE_VERBOSE")
    github_repository: str = Field("", alias="FORGE_GITHUB_REPOSITORY")

    @model_validator(mode="after")
    def distinct_review_path(self) -> Settings:
        if (self.worker_model, self.worker_base_url) == (self.reviewer_model, self.reviewer_base_url):
            raise ValueError("worker and reviewer must use independent model connections")
        return self

    @property
    def worker(self) -> ModelConnection:
        return ModelConnection(model=self.worker_model, base_url=self.worker_base_url, api_key=self.worker_api_key)

    @property
    def reviewer(self) -> ModelConnection:
        return ModelConnection(model=self.reviewer_model, base_url=self.reviewer_base_url, api_key=self.reviewer_api_key)

    @property
    def compiler(self) -> ModelConnection:
        return ModelConnection(
            model=self.compiler_model or self.reviewer_model,
            base_url=self.compiler_base_url or self.reviewer_base_url,
            api_key=self.compiler_api_key or self.reviewer_api_key,
        )

    @property
    def auditor(self) -> ModelConnection:
        return ModelConnection(
            model=self.auditor_model or self.reviewer_model,
            base_url=self.auditor_base_url or self.reviewer_base_url,
            api_key=self.auditor_api_key or self.reviewer_api_key,
        )

    def validate_connections(self) -> None:
        self.worker.require_ready("worker")
        self.reviewer.require_ready("reviewer")
        self.compiler.require_ready("compiler")
        self.auditor.require_ready("auditor")
