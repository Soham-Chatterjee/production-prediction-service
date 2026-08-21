import pytest
from fastapi.testclient import TestClient

from src.schemas.exceptions import ModelException
from src.service import main


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def valid_payload():
    return {
        "request_id": "request-123",
        "customer_id": "customer-123",
        "features": {
            "credit_score": 650,
            "age": 45,
            "tenure": 3,
            "balance": 20000.0,
            "num_of_products": 1,
            "has_cr_card": 1,
            "is_active_member": 0,
            "estimated_salary": 50000.0,
        },
    }


def test_health_returns_service_status_and_version(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "api_version": "1.0.0"}


def test_model_returns_deployed_metadata(client):
    response = client.get("/model")

    assert response.status_code == 200
    assert response.json() == {
        "model_name": "mock-churn-predictor",
        "model_version": "v1.0",
        "num_features": 8,
        "model_type": "logistic_regression",
    }


def test_predict_returns_prediction_envelope(client, valid_payload):
    response = client.post("/predict", json=valid_payload)
    body = response.json()

    assert response.status_code == 200
    assert body["response_id"]
    assert body["request_id"] == valid_payload["request_id"]
    assert 0 <= body["prediction"]["churn_probability"] <= 1
    assert body["prediction"]["prediction"] in {
        "LOW_RISK",
        "MEDIUM_RISK",
        "HIGH_RISK",
    }
    assert body["model"] == {"name": "mock-churn-predictor", "version": "v1.0"}
    assert body["metadata"]["processing_time_ms"] >= 0


def test_predict_rejects_missing_required_request_field(client, valid_payload):
    del valid_payload["customer_id"]

    response = client.post("/predict", json=valid_payload)

    print("Response:", response.json())

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Missing required information in payload: customer_id"
    }


def test_predict_rejects_missing_model_feature(client, valid_payload):
    del valid_payload["features"]["age"]
    client = TestClient(main.app, raise_server_exceptions=False)

    response = client.post("/predict", json=valid_payload)

    print("Response:", response.json())

    assert response.status_code == 422
    assert response.json() == {"detail": "Missing required features: age"}


def test_unknown_route_returns_not_found(client):
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_model_initialization_error_returns_generic_500(monkeypatch):
    class FailingEngine:
        def __init__(self):
            raise ModelException("metadata failure")

    monkeypatch.setattr("src.service.api.dependencies.PredictionEngine", FailingEngine)
    client = TestClient(main.app, raise_server_exceptions=False)

    response = client.get("/model")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Failed to initialize the prediction engine"
    }
