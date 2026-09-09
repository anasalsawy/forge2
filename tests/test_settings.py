import pytest
from pydantic import ValidationError

from forge2.settings import Settings


def test_worker_and_reviewer_must_be_independent():
    with pytest.raises(ValidationError):
        Settings(
            FORGE_WORKER_MODEL="same",
            FORGE_WORKER_BASE_URL="https://same",
            FORGE_REVIEWER_MODEL="same",
            FORGE_REVIEWER_BASE_URL="https://same",
        )


def test_connections_fail_early_when_keys_are_missing(tmp_path):
    settings = Settings(FORGE_WORKSPACE=tmp_path / "work", FORGE_STATE_DIR=tmp_path / "state")
    with pytest.raises(ValueError, match="worker model connection"):
        settings.validate_connections()
