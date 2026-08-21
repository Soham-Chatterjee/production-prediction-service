from pydantic import BaseModel

class HealthResponse(BaseModel):
    status: str
    api_version: str

class ModelMetadataResponse(BaseModel):
    model_name: str
    model_version: str
    num_features: int
    model_type: str

class PredictionResponse(BaseModel):
    response_id: str
    request_id: str
    prediction: dict
    model: dict
    metadata: dict