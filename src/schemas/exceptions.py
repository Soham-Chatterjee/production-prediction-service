class ModelException(Exception):
    """Base class for model-related exceptions."""
    pass

class InvalidModelMetadata(ModelException):
    """Raised when the model metadata is invalid."""
    pass

class MissingRequiredFeatures(ModelException):
    """Raised when required features are missing in the input."""
    pass

class APIException(Exception):
    """Base class for API-related exceptions."""
    pass

class ModelInitializationError(APIException):
    """Raised when the model fails to initialize."""
    pass

class InvalidRequest(APIException):
    """Raised when the request payload is invalid."""
    pass

class UnknownAPIException(APIException):
    """Raised for unknown API exceptions."""
    pass