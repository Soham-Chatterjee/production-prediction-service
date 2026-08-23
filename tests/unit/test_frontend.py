import json
from urllib.error import HTTPError

import pytest

from src.frontend import app
from src.schemas.exceptions import ModelInitializationError


def test_validate_features_reports_missing_values():
    assert app.validate_features({"age": 30, "balance": None}, ["age", "balance"]) == [
        "balance"
    ]


def test_build_payload_generates_request_id_and_preserves_features():
    payload = app.build_payload(" customer-1 ", {"age": 30})

    assert payload["customer_id"] == "customer-1"
    assert payload["request_id"]
    assert payload["features"] == {"age": 30}


def test_extract_prediction_returns_customer_facing_values():
    assert app.extract_prediction(
        {"prediction": {"churn_probability": 0.67, "prediction": "HIGH_RISK"}}
    ) == (0.67, "HIGH_RISK")


def test_extract_prediction_rejects_invalid_api_response():
    with pytest.raises(RuntimeError, match="invalid prediction"):
        app.extract_prediction(
            {"prediction": {"churn_probability": 1.2, "prediction": "HIGH_RISK"}}
        )


def test_request_prediction_translates_api_error(monkeypatch):
    error = HTTPError("http://api/predict", 422, "invalid", {}, None)
    error.read = lambda: json.dumps({"detail": "Missing required features: age"}).encode()
    monkeypatch.setattr(app, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(error))

    with pytest.raises(RuntimeError, match="Missing required features: age"):
        app.request_prediction("http://api", {})


def test_initialize_engine_fails_when_engine_cannot_load(monkeypatch):
    monkeypatch.setattr(app, "get_engine", lambda: (_ for _ in ()).throw(ValueError("bad metadata")))

    with pytest.raises(ModelInitializationError, match="could not be initialized"):
        app.initialize_engine()