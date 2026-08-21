from src.engine.predict import PredictionEngine
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from .api.routes import router
from src.schemas.exceptions import ModelInitializationError, InvalidRequest, UnknownAPIException

app = FastAPI(title="Production Prediction Service", version="1.0.0")
app.include_router(router)

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
