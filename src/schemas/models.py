from pydantic import BaseModel
from enum import Enum

class ModelMetadata(BaseModel):
    model_name: str
    model_version: str
    num_features: int
    model_type: str
    features: dict
    weights: dict

class ModelPrediction(BaseModel):
    request_id: str
    churn_probability: float
    prediction: str
    processing_time_ms: float

class ChurnCategory(Enum):
    LOW = "LOW_RISK"
    MEDIUM = "MEDIUM_RISK"
    HIGH = "HIGH_RISK"