from src.frontend.app import extract_prediction
from tests.integration.test_api import client, valid_payload


def test_frontend_response_shape_matches_prediction_api(client, valid_payload):
    response = client.post("/predict", json=valid_payload)

    probability, bucket = extract_prediction(response.json())

    assert response.status_code == 200
    assert 0 <= probability <= 1
    assert bucket in {"LOW_RISK", "MEDIUM_RISK", "HIGH_RISK"}