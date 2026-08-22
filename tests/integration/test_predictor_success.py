import uuid
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.schemas.requests import PredictionRequest
from fastapi.testclient import TestClient
import pytest


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


def test_predict(client):

    request = PredictionRequest(
        request_id=str(uuid.uuid4()),
        customer_id="customer_123",
        features = {
            "credit_score": 650,
            "age": 45,
            "tenure": 3,
            "balance": 20000.0,
            "num_of_products": 1,
            "has_cr_card": 1,
            "is_active_member": 0,
            "estimated_salary": 50000.0
        }
    )

    response = client.post("/predict", json=request.model_dump())

    data = response.json()
    print("Test Results:", data)

    assert response.status_code == 200
    assert "response_id" in data
    assert data["request_id"] == request.request_id
    assert "prediction" in data
    assert "model" in data
    assert "metadata" in data

