"""Command-line interface for starting, inspecting, and resuming Forge runs."""

from __future__ import annotations

import argparse
import json
import sys

from .orchestrator import Forge
from .runner import CrewAIRunner
from .settings import Settings
from .state import StateStore


def _summary(state) -> dict:
    return {
        "run_id": state.run_id,
        "status": state.status,
        "phase": state.current_phase,
        "floor": state.current_floor,
        "research_floors_completed": sum(bool(x.accepted_output) for x in state.research),
        "build_floors_completed": sum(bool(x.accepted_output) for x in state.build),
        "failure_reason": state.failure_reason,
        "state_file": str(Settings().state_dir / f"{state.run_id}.json"),
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="forge2", description="Hard-gated CrewAI research/build pipeline")
    commands = root.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--prompt", required=True)
    run.add_argument("--directive", default="")
    run.add_argument("--decision", choices=["APPROVE", "REJECT", "RERUN"])
    resume = commands.add_parser("resume")
    resume.add_argument("run_id")
    resume.add_argument("--decision", choices=["APPROVE", "REJECT", "RERUN"])
    status = commands.add_parser("status")
    status.add_argument("run_id")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    settings = Settings()
    if args.command == "status":
        state = StateStore(settings.state_dir).load(args.run_id)
    else:
        settings.validate_connections()
        forge = Forge(settings, CrewAIRunner(settings))
        if args.command == "run":
            state = forge.execute(forge.new(args.prompt, args.directive), human_decision=args.decision)
        else:
            state = forge.resume(args.run_id, human_decision=args.decision)
    print(json.dumps(_summary(state), indent=2))
    if state.status == "passed":
        return 0
    if state.status == "waiting_for_human":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())

