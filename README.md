# Forge2

Forge2 is a general-purpose CrewAI research-and-build pipeline with deterministic orchestration. The base project contains no Dual-Lobe, image, voice, or computer-use layer. Those can be integrated separately later without changing floor semantics.

## Enforced pipeline

1. Six cumulative Research Floors.
2. On every floor: Worker → independent Analyst → correction loop.
3. A failed review returns its complete feedback to the same Worker.
4. A floor advances only after an exact accepted verdict.
5. The Research Master Record is compiled only after Research Floor 6 is accepted.
6. The process persists and stops at a real human checkpoint.
7. Exact `APPROVE`, `REJECT`, or `RERUN` input controls the next action.
8. Six cumulative Build Floors use the same real correction loop.
9. A separate Final Auditor inspects the workspace and issues an exact PASS/FAIL verdict.
10. Every state transition and attempt is persisted before progression.

Strict mode is the default: `PASS_WITH_NOTES` does not release a floor. Set `FORGE_ALLOW_PASS_WITH_NOTES=true` only when explicitly desired.

## What each floor receives

Research Floor 1 receives the mission and operator directive. Later Research Floors receive the previous accepted Worker output plus the independent Analyst release notes. A correction attempt receives the same inherited floor input, the latest Worker output through the review task, and the complete latest Analyst feedback on its next Worker attempt.

Build Floor 1 receives the mission, directive, accepted Research Master Record, and workspace location. Later Build Floors additionally receive the previous accepted Builder handoff plus the previous Analyst release notes. No unrelated deliverables are inserted into the mission.

## Installation

```bash
cp .env.example .env
# Fill the worker and reviewer API keys.
uv sync --extra dev
```

The Worker and Reviewer must use different model connections. Forge2 rejects identical Worker/Reviewer model and endpoint combinations.

## Run and resume

Start research:

```bash
uv run forge2 run --prompt "Build the requested project" --directive "Optional priority"
```

Successful research exits with code `2`, meaning the persisted run is waiting for a human—not failed. Review `.forge2/<run_id>.json`, then resume:

```bash
uv run forge2 resume <run_id> --decision APPROVE
```

Other exact decisions:

```bash
uv run forge2 resume <run_id> --decision REJECT
uv run forge2 resume <run_id> --decision RERUN
```

Inspect without invoking any model:

```bash
uv run forge2 status <run_id>
```

## Output contracts

Floor reviews must end with exactly one of:

```text
VERDICT: PASS
VERDICT: CORRECTION_REQUIRED
VERDICT: PASS_WITH_NOTES
```

The final audit must end with exactly:

```text
FINAL_VERDICT: PASS
```

or:

```text
FINAL_VERDICT: FAIL
```

Quoted, negated, embedded, or non-final phrases never pass a gate.

## Tools

Builders have workspace-bounded file reading, file writing, directory listing, shell execution, Git, validation, and optional GitHub access. Reviewers receive read/list/shell/Git/validation capabilities but cannot modify files. All subprocess tools return explicit exit codes. Validation succeeds only when its process exits with code zero.

GitHub access is opt-in through `GITHUB_TOKEN` and `FORGE_GITHUB_REPOSITORY=owner/name`. There is no hardcoded repository target.

## Durable evidence

Each run produces:

- `.forge2/<run_id>.json`: complete crash-safe current state
- `.forge2/<run_id>.events.jsonl`: append-only transition and verdict record

State writes use a flushed temporary file followed by atomic replacement. A run can resume after a process restart.

## Validation

```bash
uv run ruff check src tests
uv run pytest
```

CI runs both commands for pushes and pull requests.

