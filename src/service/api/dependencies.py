from src.engine.predict import PredictionEngine
from src.schemas.exceptions import ModelException, ModelInitializationError

def get_engine() -> PredictionEngine:
    """
    Dependency function to provide the PredictionEngine instance.
    """
    try:
        engine = PredictionEngine()
        return engine
    except ModelException as e:
        raise ModelInitializationError("Failed to initialize the prediction engine due to missing metadata.") from e
