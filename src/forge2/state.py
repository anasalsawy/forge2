"""Crash-safe run state and complete floor records."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class AttemptRecord(BaseModel):
    attempt: int
    worker_output: str
    analyst_output: str
    verdict: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class FloorRecord(BaseModel):
    phase: Literal["research", "build"]
    floor: int
    input_handoff: str
    attempts: list[AttemptRecord] = Field(default_factory=list)
    accepted_output: str = ""
    analyst_notes: str = ""


class RunState(BaseModel):
    run_id: str
    prompt: str
    directive: str = ""
    status: str = "created"
    current_phase: str = "research"
    current_floor: int = 1
    research: list[FloorRecord] = Field(default_factory=list)
    research_master_record: str = ""
    human_decision: str = ""
    build: list[FloorRecord] = Field(default_factory=list)
    final_audit: str = ""
    failure_reason: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class StateStore:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

    def path(self, run_id: str) -> Path:
        if not run_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in run_id):
            raise ValueError("invalid run_id")
        return self.directory / f"{run_id}.json"

    def save(self, state: RunState) -> Path:
        state.updated_at = datetime.now(UTC).isoformat()
        target = self.path(state.run_id)
        fd, temporary = tempfile.mkstemp(prefix=f".{state.run_id}-", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(state.model_dump_json(indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return target

    def load(self, run_id: str) -> RunState:
        return RunState.model_validate_json(self.path(run_id).read_text(encoding="utf-8"))

    def events_path(self, run_id: str) -> Path:
        return self.directory / f"{run_id}.events.jsonl"

    def event(self, run_id: str, kind: str, payload: dict) -> None:
        record = {"at": datetime.now(UTC).isoformat(), "kind": kind, "payload": payload}
        with self.events_path(run_id).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

