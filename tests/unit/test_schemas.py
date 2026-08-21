import pytest
from pydantic import ValidationError

from src.schemas.models import ModelMetadata, ModelPrediction
from src.schemas.requests import PredictionRequest
from src.schemas.responses import (
    HealthResponse,
    ModelMetadataResponse,
    PredictionResponse,
)


def test_prediction_request_accepts_valid_payload():
    request = PredictionRequest(
        request_id="request-1",
        customer_id="customer-1",
        features={"age": 30},
    )

    assert request.request_id == "request-1"
    assert request.features == {"age": 30}


@pytest.mark.parametrize("field", ["request_id", "customer_id", "features"])
def test_prediction_request_requires_all_fields(field):
    payload = {
        "request_id": "request-1",
        "customer_id": "customer-1",
        "features": {},
    }
    del payload[field]

    with pytest.raises(ValidationError):
        PredictionRequest(**payload)


def test_model_metadata_requires_feature_and_weight_maps():
    payload = {
        "model_name": "model",
        "model_version": "1",
        "num_features": 1,
        "model_type": "test",
    }

    with pytest.raises(ValidationError):
        ModelMetadata(**payload)


def test_model_prediction_requires_processing_time():
    payload = {
        "request_id": "request-1",
        "churn_probability": 0.5,
        "prediction": "MEDIUM_RISK",
    }

    with pytest.raises(ValidationError):
        ModelPrediction(**payload)


def test_response_models_serialize_expected_fields():
    health = HealthResponse(status="healthy", api_version="1.0")
    metadata = ModelMetadataResponse(
        model_name="model",
        model_version="1",
        num_features=1,
        model_type="test",
    )
    prediction = PredictionResponse(
        response_id="response-1",
        request_id="request-1",
        prediction={"prediction": "LOW_RISK"},
        model={"name": "model", "version": "1"},
        metadata={"processing_time_ms": 0.1},
    )

    assert health.model_dump() == {"status": "healthy", "api_version": "1.0"}
    assert metadata.num_features == 1
    assert prediction.request_id == "request-1"
