import uuid
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.schemas.requests import PredictionRequest
from fastapi.testclient import TestClient
from src.service.main import app

client = TestClient(app)

def test_predict():

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

