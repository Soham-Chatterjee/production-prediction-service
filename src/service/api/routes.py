from fastapi import APIRouter, Depends, Request
from src.engine.predict import PredictionEngine
from .dependencies import get_engine
from src.schemas.responses import HealthResponse, ModelMetadataResponse, PredictionResponse
from src.schemas.requests import PredictionRequest
from src.schemas.exceptions import InvalidRequest, MissingRequiredFeatures, UnknownAPIException, ModelInitializationError

import uuid
import time

router = APIRouter()


def _get_engine_from_state(request: Request) -> PredictionEngine:
    """Helper to safely retrieve the engine from app state."""
    # Check if there was an initialization error
    if hasattr(request.app.state, "initialization_error") and request.app.state.initialization_error:
        raise request.app.state.initialization_error
    
    if not hasattr(request.app.state, "engine") or request.app.state.engine is None:
        raise ModelInitializationError("Prediction engine not initialized")
    return request.app.state.engine

@router.get("/health", tags=["Health Check"], response_model=HealthResponse)
def health_check(request: Request):
    """
    Health check endpoint to verify that the service is running.
    """
    return HealthResponse(status="healthy", api_version=request.app.version)

@router.get("/model", tags=["Model"], response_model=ModelMetadataResponse)
def get_model_metadata(request: Request):
    """
    Endpoint to retrieve the metadata of the deployed model.
    """
    engine = _get_engine_from_state(request)
    metadata = engine.get_metadata()
    return ModelMetadataResponse(
        model_name=metadata.model_name,
        model_version=metadata.model_version,
        num_features=metadata.num_features,
        model_type=metadata.model_type
    )

@router.post("/predict", tags=["Prediction"], response_model=PredictionResponse)
def predict(prediction_request: PredictionRequest, request: Request):
    """
    Endpoint to make predictions using the deployed model.
    """
    engine_lookup_started = time.perf_counter()
    engine = _get_engine_from_state(request)
    engine_lookup_ms = (time.perf_counter() - engine_lookup_started) * 1000

    feature_validation_started = time.perf_counter()
    expected_features = set(engine.metadata.features.keys())
    missing_features = expected_features - set(prediction_request.features.keys())
    feature_validation_ms = (time.perf_counter() - feature_validation_started) * 1000

    if missing_features:
        raise InvalidRequest(f"Missing required features: {', '.join(sorted(missing_features))}")
    
    try:
        prediction_started = time.perf_counter()
        prediction = engine.predict(prediction_request)
        prediction_ms = (time.perf_counter() - prediction_started) * 1000

        response_started = time.perf_counter()
        response = PredictionResponse(
            response_id=str(uuid.uuid4()),
            request_id=prediction_request.request_id,
            prediction={
                "churn_probability": prediction.churn_probability,
                "prediction": prediction.prediction,
            },
            model={
                "name": engine.metadata.model_name,
                "version": engine.metadata.model_version
            },
            metadata={
                "processing_time_ms": prediction.processing_time_ms
            }
        )
        request.state.prediction_timing = {
            "engine_lookup_ms": engine_lookup_ms,
            "feature_validation_ms": feature_validation_ms,
            "prediction_ms": prediction_ms,
            "response_creation_ms": (time.perf_counter() - response_started) * 1000,
        }
        return response
    except MissingRequiredFeatures as e:
        raise InvalidRequest(str(e)) from e

    except Exception as e:
        raise UnknownAPIException(f"An unexpected error occurred: {e}") from e