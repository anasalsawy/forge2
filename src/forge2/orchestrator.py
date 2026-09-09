"""Deterministic Forge state machine with real correction loops and resumability."""

from __future__ import annotations

import uuid

from .contracts import (
    FinalVerdict,
    FloorVerdict,
    HumanDecision,
    parse_final_verdict,
    parse_floor_review,
    parse_human_decision,
)
from .prompts import (
    BUILD_ANALYST_TASK,
    BUILD_WORKER_TASK,
    FINAL_AUDIT_TASK,
    RESEARCH_ANALYST_TASK,
    RESEARCH_COMPILER_TASK,
    RESEARCH_WORKER_TASK,
)
from .runner import Runner
from .settings import Settings
from .state import AttemptRecord, FloorRecord, RunState, StateStore


class FloorFailure(RuntimeError):
    pass


class Forge:
    def __init__(self, settings: Settings, runner: Runner):
        self.settings = settings
        self.runner = runner
        self.store = StateStore(settings.state_dir)

    @property
    def attempt_limit(self) -> int:
        return 1 + self.settings.max_corrections

    def new(self, prompt: str, directive: str = "") -> RunState:
        if not prompt.strip():
            raise ValueError("prompt is required; Forge2 never substitutes an unrelated default mission")
        state = RunState(run_id=uuid.uuid4().hex, prompt=prompt.strip(), directive=directive.strip())
        self.store.save(state)
        self.store.event(state.run_id, "run_created", {"prompt": state.prompt, "directive": state.directive})
        return state

    def execute(self, state: RunState, human_decision: str | None = None) -> RunState:
        try:
            if not state.research_master_record:
                self._research(state)
            if state.status in {"waiting_for_human", "research_complete"}:
                if not human_decision:
                    state.status = "waiting_for_human"
                    self.store.save(state)
                    return state
                decision = parse_human_decision(human_decision)
                state.human_decision = decision.value
                self.store.event(state.run_id, "human_decision", {"decision": decision.value})
                if decision is HumanDecision.REJECT:
                    state.status = "rejected"
                    state.failure_reason = "The human reviewer rejected the Research Master Record."
                    self.store.save(state)
                    return state
                if decision is HumanDecision.RERUN:
                    state.research.clear()
                    state.research_master_record = ""
                    state.build.clear()
                    state.final_audit = ""
                    state.human_decision = ""
                    state.status = "created"
                    self.store.save(state)
                    self._research(state)
                    state.status = "waiting_for_human"
                    self.store.save(state)
                    return state
            if state.human_decision != HumanDecision.APPROVE.value:
                state.status = "waiting_for_human"
                self.store.save(state)
                return state
            if len(state.build) < self.settings.build_floors:
                self._build(state)
            self._audit(state)
        except Exception as exc:  # noqa: BLE001 - every execution failure must be persisted
            state.status = "failed"
            state.failure_reason = str(exc)
            self.store.event(state.run_id, "run_failed", {"phase": state.current_phase, "floor": state.current_floor, "error": str(exc)})
            self.store.save(state)
            return state
        self.store.save(state)
        return state

    def resume(self, run_id: str, human_decision: str | None = None) -> RunState:
        return self.execute(self.store.load(run_id), human_decision=human_decision)

    def _accepted(self, verdict: FloorVerdict) -> bool:
        return verdict is FloorVerdict.PASS or (
            verdict is FloorVerdict.PASS_WITH_NOTES and self.settings.allow_pass_with_notes
        )

    def _research(self, state: RunState) -> None:
        state.current_phase = "research"
        pending = state.research[-1] if state.research and not state.research[-1].accepted_output else None
        accepted = [record for record in state.research if record.accepted_output]
        previous = accepted[-1].accepted_output + "\n\nINDEPENDENT ANALYST RELEASE NOTES:\n" + accepted[-1].analyst_notes if accepted else "NONE — establish the first complete state."
        start = pending.floor if pending else len(accepted) + 1
        for floor in range(start, self.settings.research_floors + 1):
            state.current_floor = floor
            if pending and pending.floor == floor:
                record = pending
                feedback = record.attempts[-1].analyst_output if record.attempts else "NONE"
            else:
                record = FloorRecord(phase="research", floor=floor, input_handoff=previous)
                state.research.append(record)
                feedback = "NONE"
            for attempt in range(len(record.attempts) + 1, self.attempt_limit + 1):
                worker_task = RESEARCH_WORKER_TASK.format(prompt=state.prompt, directive=state.directive or "NONE", floor=floor, floor_count=self.settings.research_floors, attempt=attempt, attempt_limit=self.attempt_limit, previous_handoff=previous, analyst_feedback=feedback)
                worker = self.runner.research_worker(worker_task)
                review_task = RESEARCH_ANALYST_TASK.format(prompt=state.prompt, floor=floor, floor_count=self.settings.research_floors, attempt=attempt, attempt_limit=self.attempt_limit, previous_handoff=previous, worker_output=worker)
                review = self.runner.research_analyst(review_task)
                parsed = parse_floor_review(review)
                record.attempts.append(AttemptRecord(attempt=attempt, worker_output=worker, analyst_output=review, verdict=parsed.verdict.value))
                self.store.event(state.run_id, "research_attempt", {"floor": floor, "attempt": attempt, "verdict": parsed.verdict.value})
                self.store.save(state)
                if self._accepted(parsed.verdict):
                    record.accepted_output = worker
                    record.analyst_notes = review
                    break
                feedback = review
            if not record.accepted_output:
                raise FloorFailure(f"Research Floor {floor} exhausted {self.attempt_limit} attempts without an accepted verdict. Last review: {feedback}")
            previous = record.accepted_output + "\n\nINDEPENDENT ANALYST RELEASE NOTES:\n" + record.analyst_notes
            pending = None
            self.store.save(state)
        records = "\n\n".join(f"=== RESEARCH FLOOR {r.floor} ===\nWORKER:\n{r.accepted_output}\nANALYST:\n{r.analyst_notes}" for r in state.research)
        state.research_master_record = self.runner.compiler(RESEARCH_COMPILER_TASK.format(prompt=state.prompt, research_records=records))
        state.status = "waiting_for_human"
        self.store.event(state.run_id, "research_compiled", {"floors": len(state.research)})
        self.store.save(state)

    def _build(self, state: RunState) -> None:
        state.current_phase = "build"
        pending = state.build[-1] if state.build and not state.build[-1].accepted_output else None
        accepted = [record for record in state.build if record.accepted_output]
        previous = accepted[-1].accepted_output + "\n\nINDEPENDENT ANALYST RELEASE NOTES:\n" + accepted[-1].analyst_notes if accepted else "NONE — inspect the workspace and establish the first complete implementation."
        start = pending.floor if pending else len(accepted) + 1
        workspace = str(self.settings.workspace.resolve())
        for floor in range(start, self.settings.build_floors + 1):
            state.current_floor = floor
            if pending and pending.floor == floor:
                record = pending
                feedback = record.attempts[-1].analyst_output if record.attempts else "NONE"
            else:
                record = FloorRecord(phase="build", floor=floor, input_handoff=previous)
                state.build.append(record)
                feedback = "NONE"
            for attempt in range(len(record.attempts) + 1, self.attempt_limit + 1):
                worker_task = BUILD_WORKER_TASK.format(prompt=state.prompt, directive=state.directive or "NONE", floor=floor, floor_count=self.settings.build_floors, attempt=attempt, attempt_limit=self.attempt_limit, workspace=workspace, research_master=state.research_master_record, previous_handoff=previous, analyst_feedback=feedback)
                worker = self.runner.builder(worker_task)
                review_task = BUILD_ANALYST_TASK.format(prompt=state.prompt, floor=floor, floor_count=self.settings.build_floors, attempt=attempt, attempt_limit=self.attempt_limit, workspace=workspace, research_master=state.research_master_record, previous_handoff=previous, worker_output=worker)
                review = self.runner.build_analyst(review_task)
                parsed = parse_floor_review(review)
                record.attempts.append(AttemptRecord(attempt=attempt, worker_output=worker, analyst_output=review, verdict=parsed.verdict.value))
                self.store.event(state.run_id, "build_attempt", {"floor": floor, "attempt": attempt, "verdict": parsed.verdict.value})
                self.store.save(state)
                if self._accepted(parsed.verdict):
                    record.accepted_output = worker
                    record.analyst_notes = review
                    break
                feedback = review
            if not record.accepted_output:
                raise FloorFailure(f"Build Floor {floor} exhausted {self.attempt_limit} attempts without an accepted verdict. Last review: {feedback}")
            previous = record.accepted_output + "\n\nINDEPENDENT ANALYST RELEASE NOTES:\n" + record.analyst_notes
            pending = None
            self.store.save(state)

    def _audit(self, state: RunState) -> None:
        state.current_phase = "audit"
        workspace = str(self.settings.workspace.resolve())
        records = "\n\n".join(f"=== BUILD FLOOR {r.floor} ===\nWORKER:\n{r.accepted_output}\nANALYST:\n{r.analyst_notes}" for r in state.build)
        audit = self.runner.auditor(FINAL_AUDIT_TASK.format(prompt=state.prompt, workspace=workspace, research_master=state.research_master_record, build_records=records))
        state.final_audit = audit
        verdict = parse_final_verdict(audit)
        state.status = "passed" if verdict is FinalVerdict.PASS else "failed"
        if verdict is FinalVerdict.FAIL:
            state.failure_reason = audit
        self.store.event(state.run_id, "final_audit", {"verdict": verdict.value})
