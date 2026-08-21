from pathlib import Path
from src.schemas.requests import PredictionRequest
from src.schemas.exceptions import InvalidModelMetadata, MissingRequiredFeatures
from src.schemas.models import ModelMetadata, ModelPrediction, ChurnCategory
import json
import math
import time

class PredictionEngine():
    def __init__(self):
        metadata_path = Path(__file__).parent / "metadata.json"
        self.required_model_metadata = ["model_name", "model_version", "num_features", "model_type"]
        self.required_features = ["credit_score", "age", "tenure", "balance", "num_of_products", "has_cr_card", "is_active_member", "estimated_salary"]

        with metadata_path.open("r", encoding="utf-8") as file:
            metadata = json.load(file)


        missing_metadata = [key for key in self.required_model_metadata if key not in metadata]

        if missing_metadata:
            raise InvalidModelMetadata(f"Model couldn't be initialized. Missing required metadata fields: {', '.join(missing_metadata)}")

        metadata_object = ModelMetadata(**metadata)
        self.metadata = metadata_object

    def get_metadata(self) -> ModelMetadata:
        return self.metadata

    def calculate_log_odds(self, features: dict) -> float:
        # Logic to calculate log odds based on the features
        log_odds = self.metadata.weights.get("intercept", 0)  # Start with the intercept
        for feature in self.required_features:
            log_odds += features.get(feature, 0) * self.metadata.weights.get(feature, 0)  # Use the weight from metadata
        return log_odds

    def calculate_probability(self, log_odds: float) -> float:
        # Convert log odds to probability using the logistic function
        return round(1 / (1 + math.exp(-log_odds)), 2)

    def predict(self, request: PredictionRequest) -> dict:
        # Implement the prediction logic using the model and features
        features = request.features
        missing_features = [feature for feature in self.required_features if feature not in features]
        if missing_features:
            raise MissingRequiredFeatures(f"Missing required features: {', '.join(missing_features)}")
        
        start_time = time.perf_counter()
        log_odds = self.calculate_log_odds(features)
        probability = self.calculate_probability(log_odds)
        prediction = ChurnCategory.LOW if probability < 0.33 else (ChurnCategory.MEDIUM if probability < 0.67 else ChurnCategory.HIGH)
        end_time = time.perf_counter()

        return ModelPrediction(
            request_id=request.request_id,
            churn_probability=probability,
            prediction=prediction.value,
            processing_time_ms=round((end_time - start_time) * 1000, 2)
        )