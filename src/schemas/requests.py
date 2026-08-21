from pydantic import BaseModel

class PredictionRequest(BaseModel):
    request_id: str
    customer_id: str
    features: dict