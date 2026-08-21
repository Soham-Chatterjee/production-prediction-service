import pytest

from src.schemas.exceptions import ModelException, ModelInitializationError
from src.service.api import dependencies


def test_get_engine_returns_initialized_engine():
    engine = dependencies.get_engine()

    assert engine.get_metadata().model_name == "mock-churn-predictor"


def test_get_engine_translates_model_exception(monkeypatch):
    def fail_initialization():
        raise ModelException("metadata is invalid")

    monkeypatch.setattr(dependencies, "PredictionEngine", fail_initialization)

    with pytest.raises(ModelInitializationError, match="Failed to initialize") as error:
        dependencies.get_engine()

    assert isinstance(error.value.__cause__, ModelException)
