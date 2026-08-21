import json

import pytest

from src.engine.predict import PredictionEngine
from src.schemas.exceptions import InvalidModelMetadata, MissingRequiredFeatures
from src.schemas.requests import PredictionRequest
from src.schemas.models import ChurnCategory


@pytest.fixture
def engine():
    return PredictionEngine()


@pytest.fixture
def valid_features():
    return {
        "credit_score": 650,
        "age": 45,
        "tenure": 3,
        "balance": 20000.0,
        "num_of_products": 1,
        "has_cr_card": 1,
        "is_active_member": 0,
        "estimated_salary": 50000.0,
    }


def make_request(features):
    return PredictionRequest(
        request_id="request-123",
        customer_id="customer-123",
        features=features,
    )


def test_loads_model_metadata(engine):
    metadata = engine.get_metadata()

    assert metadata.model_name == "mock-churn-predictor"
    assert metadata.model_version == "v1.0"
    assert metadata.num_features == 8
    assert metadata.model_type == "logistic_regression"
    assert set(engine.required_features) == set(metadata.features)


def test_rejects_metadata_missing_required_field(monkeypatch):
    def fake_open(*args, **kwargs):
        from io import StringIO

        metadata = {
            "model_version": "v1.0",
            "num_features": 8,
            "model_type": "logistic_regression",
        }
        return StringIO(json.dumps(metadata))

    monkeypatch.setattr("pathlib.Path.open", fake_open)

    with pytest.raises(InvalidModelMetadata, match="model_name"):
        PredictionEngine()


def test_calculate_log_odds_uses_intercept_and_feature_weights(engine):
    features = {feature: 0 for feature in engine.required_features}
    features["age"] = 10

    assert engine.calculate_log_odds(features) == pytest.approx(0.3)


def test_calculate_log_odds_defaults_missing_values_to_zero(engine):
    assert engine.calculate_log_odds({}) == pytest.approx(-0.2)


@pytest.mark.parametrize(
    ("log_odds", "expected"),
    [(-100, 0.0), (0, 0.5), (100, 1.0)],
)
def test_calculate_probability_rounds_logistic_result(engine, log_odds, expected):
    assert engine.calculate_probability(log_odds) == expected


@pytest.mark.parametrize(
    ("log_odds", "category"),
    [(-10, ChurnCategory.LOW), (0, ChurnCategory.MEDIUM), (10, ChurnCategory.HIGH)],
)
def test_predict_assigns_risk_category(engine, valid_features, log_odds, category, monkeypatch):
    monkeypatch.setattr(engine, "calculate_log_odds", lambda features: log_odds)

    result = engine.predict(make_request(valid_features))

    assert result.prediction == category.value


def test_predict_returns_request_id_probability_and_processing_time(engine, valid_features):
    result = engine.predict(make_request(valid_features))

    assert result.request_id == "request-123"
    assert 0 <= result.churn_probability <= 1
    assert result.processing_time_ms >= 0


def test_predict_rejects_missing_required_features(engine, valid_features):
    del valid_features["age"]

    with pytest.raises(MissingRequiredFeatures, match="age"):
        engine.predict(make_request(valid_features))
