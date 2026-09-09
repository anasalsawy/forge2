
from forge2.orchestrator import Forge
from forge2.settings import Settings
from forge2.state import AttemptRecord, FloorRecord


class ScriptedRunner:
    def __init__(self, research_reviews=None, build_reviews=None, audit="audit\nFINAL_VERDICT: PASS"):
        self.research_reviews = iter(research_reviews or [])
        self.build_reviews = iter(build_reviews or [])
        self.audit_output = audit
        self.calls = []

    def research_worker(self, task):
        self.calls.append(("research_worker", task))
        return "research cumulative output"

    def research_analyst(self, task):
        self.calls.append(("research_analyst", task))
        return next(self.research_reviews, "verified\nVERDICT: PASS")

    def compiler(self, task):
        self.calls.append(("compiler", task))
        return "master record"

    def builder(self, task):
        self.calls.append(("builder", task))
        return "build cumulative output"

    def build_analyst(self, task):
        self.calls.append(("build_analyst", task))
        return next(self.build_reviews, "verified\nVERDICT: PASS")

    def auditor(self, task):
        self.calls.append(("auditor", task))
        return self.audit_output


def config(tmp_path, **kwargs):
    return Settings(
        FORGE_WORKER_API_KEY="w",
        FORGE_REVIEWER_API_KEY="r",
        FORGE_RESEARCH_FLOORS=kwargs.pop("research_floors", 2),
        FORGE_BUILD_FLOORS=kwargs.pop("build_floors", 2),
        FORGE_MAX_CORRECTIONS=kwargs.pop("max_corrections", 2),
        FORGE_WORKSPACE=tmp_path / "work",
        FORGE_STATE_DIR=tmp_path / "state",
        **kwargs,
    )


def test_real_correction_loop_and_feedback(tmp_path):
    runner = ScriptedRunner(research_reviews=["gap A\nVERDICT: CORRECTION_REQUIRED", "fixed\nVERDICT: PASS"])
    forge = Forge(config(tmp_path, research_floors=1, build_floors=1), runner)
    state = forge.execute(forge.new("Build the requested thing"))
    assert state.status == "waiting_for_human"
    assert len(state.research[0].attempts) == 2
    second_worker_prompt = [task for kind, task in runner.calls if kind == "research_worker"][1]
    assert "gap A" in second_worker_prompt


def test_human_checkpoint_really_waits_and_resumes(tmp_path):
    runner = ScriptedRunner()
    forge = Forge(config(tmp_path), runner)
    waiting = forge.execute(forge.new("Mission"))
    assert waiting.status == "waiting_for_human"
    assert not any(kind == "builder" for kind, _ in runner.calls)
    passed = forge.resume(waiting.run_id, "APPROVE")
    assert passed.status == "passed"
    assert sum(kind == "builder" for kind, _ in runner.calls) == 2


def test_reject_never_builds(tmp_path):
    runner = ScriptedRunner()
    forge = Forge(config(tmp_path), runner)
    state = forge.execute(forge.new("Mission"), "REJECT")
    assert state.status == "rejected"
    assert not any(kind == "builder" for kind, _ in runner.calls)


def test_strict_mode_rejects_pass_with_notes(tmp_path):
    reviews = ["notes\nVERDICT: PASS_WITH_NOTES"] * 2
    runner = ScriptedRunner(research_reviews=reviews)
    forge = Forge(config(tmp_path, research_floors=1, max_corrections=1), runner)
    state = forge.execute(forge.new("Mission"))
    assert state.status == "failed"
    assert "Research Floor 1 exhausted" in state.failure_reason


def test_analyst_release_notes_reach_next_floor(tmp_path):
    runner = ScriptedRunner()
    forge = Forge(config(tmp_path, research_floors=2), runner)
    forge.execute(forge.new("Mission"))
    second = [task for kind, task in runner.calls if kind == "research_worker"][1]
    assert "INDEPENDENT ANALYST RELEASE NOTES" in second


def test_no_voice_image_or_computer_use_is_forced(tmp_path):
    runner = ScriptedRunner()
    forge = Forge(config(tmp_path, research_floors=1, build_floors=1), runner)
    state = forge.execute(forge.new("Build a CSV parser"))
    forge.resume(state.run_id, "APPROVE")
    builder_prompt = next(task for kind, task in runner.calls if kind == "builder")
    assert "VOICE REAL-TIME" not in builder_prompt
    assert "IMAGE GENERATION LAYER" not in builder_prompt
    assert "COMPUTER-USE LAYER" not in builder_prompt


def test_resume_continues_pending_floor_instead_of_skipping_it(tmp_path):
    runner = ScriptedRunner()
    forge = Forge(config(tmp_path, research_floors=2, max_corrections=2), runner)
    state = forge.new("Mission")
    state.research.append(
        FloorRecord(
            phase="research",
            floor=1,
            input_handoff="NONE",
            attempts=[
                AttemptRecord(
                    attempt=1,
                    worker_output="incomplete",
                    analyst_output="fix the evidence\nVERDICT: CORRECTION_REQUIRED",
                    verdict="CORRECTION_REQUIRED",
                )
            ],
        )
    )
    forge.store.save(state)
    resumed = forge.resume(state.run_id)
    assert resumed.status == "waiting_for_human"
    assert len(resumed.research) == 2
    assert resumed.research[0].attempts[-1].attempt == 2
    first_prompt = next(task for kind, task in runner.calls if kind == "research_worker")
    assert "fix the evidence" in first_prompt
