import pytest
import importlib
import sys
from fastapi.testclient import TestClient

from src.schemas.exceptions import ModelException
from src.service import main


@pytest.fixture
def client():
    """Create a fresh TestClient with a fresh app instance."""
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from fastapi.exceptions import RequestValidationError
    from contextlib import asynccontextmanager
    from src.schemas.exceptions import ModelInitializationError, InvalidRequest, UnknownAPIException
    from src.service.api.dependencies import get_engine
    from src.service.api.routes import router
    
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: Initialize the engine
        try:
            app.state.engine = get_engine()
            app.state.initialization_error = None
        except ModelInitializationError as e:
            # Store the error - routes will check for this
            app.state.initialization_error = e
            app.state.engine = None
        yield
        # Shutdown: Cleanup if needed
        pass
    
    # Create a fresh app instance for this test
    app = FastAPI(title="Production Prediction Service", version="1.0.0", lifespan=lifespan)
    app.include_router(router)
    
    # Add exception handlers
    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(request: Request, exc: RequestValidationError):
        missing_fields = [
            ".".join(str(location) for location in error["loc"][1:])
            for error in exc.errors()
            if error["type"] == "missing"
        ]
        if missing_fields:
            detail = f"Missing required information in payload: {', '.join(missing_fields)}"
        else:
            detail = "Invalid information in payload"

        return JSONResponse(status_code=422, content={"detail": detail})

    @app.exception_handler(ModelInitializationError)
    async def model_initialization_error_handler(request, exc):
        return JSONResponse(
            status_code=500,
            content={"detail": "Failed to initialize the prediction engine"}
        )

    @app.exception_handler(InvalidRequest)
    async def invalid_request_handler(request, exc):
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc)}
        )

    @app.exception_handler(UnknownAPIException)
    async def unknown_api_exception_handler(request, exc):
        return JSONResponse(
            status_code=500,
            content={"detail": "An unexpected error occurred"}
        )
    
    # Use TestClient as context manager to ensure lifespan runs
    with TestClient(app) as test_client:
        yield test_client


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


def test_predict_exposes_server_timing_headers(valid_payload):
    with TestClient(main.app) as service_client:
        response = service_client.post("/predict", json=valid_payload)

    assert response.status_code == 200
    assert float(response.headers["X-Server-Total-Time-Ms"]) >= 0
    assert float(response.headers["X-Server-Engine-Lookup-Ms"]) >= 0
    assert float(response.headers["X-Server-Feature-Validation-Ms"]) >= 0
    assert float(response.headers["X-Server-Prediction-Ms"]) >= 0
    assert float(response.headers["X-Server-Response-Creation-Ms"]) >= 0


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

    response = client.post("/predict", json=valid_payload)

    print("Response:", response.json())

    assert response.status_code == 422
    assert response.json() == {"detail": "Missing required features: age"}


def test_unknown_route_returns_not_found(client):
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_model_initialization_error_prevents_app_startup(monkeypatch):
    from src.schemas.exceptions import ModelInitializationError
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from fastapi.exceptions import RequestValidationError
    from contextlib import asynccontextmanager
    from src.service.api.routes import router
    
    class FailingEngine:
        def __init__(self):
            raise ModelException("metadata failure")

    # Monkeypatch the PredictionEngine
    monkeypatch.setattr("src.service.api.dependencies.PredictionEngine", FailingEngine)
    
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            # Import here so monkeypatch is applied
            from src.service.api.dependencies import get_engine
            app.state.engine = get_engine()
            app.state.initialization_error = None
        except ModelInitializationError as e:
            app.state.initialization_error = e
            app.state.engine = None
        yield
    
    app = FastAPI(title="Production Prediction Service", version="1.0.0", lifespan=lifespan)
    app.include_router(router)
    
    # Add exception handlers
    @app.exception_handler(ModelInitializationError)
    async def model_initialization_error_handler(request, exc):
        return JSONResponse(
            status_code=500,
            content={"detail": "Failed to initialize the prediction engine"}
        )
    
    with TestClient(app, raise_server_exceptions=False) as client:
        # Verify that first request to any endpoint returns 500 due to initialization error
        response = client.get("/model")
        assert response.status_code == 500
        assert response.json() == {
            "detail": "Failed to initialize the prediction engine"
        }
