"""Streamlit frontend for the churn prediction service."""

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
	sys.path.insert(0, str(PROJECT_ROOT))

from src.schemas.exceptions import ModelInitializationError
from src.service.api.dependencies import get_engine


DEFAULT_API_URL = "http://127.0.0.1:8000"
REQUEST_TIMEOUT_SECONDS = 10


def initialize_engine() -> Any:
	"""Load model metadata before rendering the UI."""
	try:
		return get_engine()
	except Exception as exc:
		raise ModelInitializationError(
			"The prediction engine could not be initialized."
		) from exc


def validate_features(features: dict[str, Any], required_features: list[str]) -> list[str]:
	"""Return required feature names that have no usable input value."""
	return [
		feature
		for feature in required_features
		if feature not in features or features[feature] is None
	]


def build_payload(customer_id: str, features: dict[str, Any]) -> dict[str, Any]:
	"""Build the API payload while keeping request IDs technical."""
	return {
		"request_id": str(uuid.uuid4()),
		"customer_id": customer_id.strip(),
		"features": features,
	}


def request_prediction(
	api_url: str,
	payload: dict[str, Any],
	timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
	"""Call the prediction endpoint and return its decoded response."""
	request = Request(
		f"{api_url.rstrip('/')}/predict",
		data=json.dumps(payload).encode("utf-8"),
		headers={"Content-Type": "application/json"},
		method="POST",
	)
	try:
		with urlopen(request, timeout=timeout) as response:
			return json.loads(response.read().decode("utf-8"))
	except HTTPError as exc:
		try:
			detail = json.loads(exc.read().decode("utf-8")).get("detail")
		except (ValueError, UnicodeDecodeError):
			detail = None
		raise RuntimeError(detail or "The prediction service rejected the request.") from exc
	except (URLError, TimeoutError, OSError) as exc:
		raise RuntimeError(
			"The prediction service is unavailable. Check that the API is running."
		) from exc
	except (ValueError, TypeError) as exc:
		raise RuntimeError("The prediction service returned an invalid response.") from exc


def extract_prediction(response: dict[str, Any]) -> tuple[float, str]:
	"""Extract and validate only customer-facing prediction values."""
	try:
		probability = float(response["prediction"]["churn_probability"])
		bucket = str(response["prediction"]["prediction"])
	except (KeyError, TypeError, ValueError) as exc:
		raise RuntimeError("The prediction service returned an incomplete response.") from exc

	if not 0 <= probability <= 1 or bucket not in {"LOW_RISK", "MEDIUM_RISK", "HIGH_RISK"}:
		raise RuntimeError("The prediction service returned an invalid prediction.")
	return probability, bucket


def main() -> None:
	import streamlit as st

	try:
		engine = initialize_engine()
	except ModelInitializationError as exc:
		st.error(str(exc))
		st.stop()

	st.set_page_config(page_title="Customer Churn Prediction")
	st.title("Customer Churn Prediction")
	st.caption("Enter customer information to estimate churn risk.")

	customer_id = st.text_input("Customer ID", placeholder="e.g. customer-123")
	st.subheader("Customer details")
	features = {
		"credit_score": st.number_input("Credit score", min_value=0, max_value=850, value=650),
		"age": st.number_input("Age", min_value=0, max_value=120, value=45),
		"tenure": st.number_input("Tenure (months)", min_value=0, value=3),
		"balance": st.number_input("Account balance", min_value=0.0, value=20000.0),
		"num_of_products": st.number_input("Number of products", min_value=0, value=1),
		"has_cr_card": st.checkbox("Has a credit card"),
		"is_active_member": st.checkbox("Is an active member"),
		"estimated_salary": st.number_input("Estimated salary", min_value=0.0, value=50000.0),
	}

	if st.button("Predict Churn Probability", type="primary"):
		missing_features = validate_features(features, list(engine.metadata.features))
		if not customer_id.strip():
			st.error("Customer ID is required.")
		elif missing_features:
			st.error("Please provide all customer details before predicting.")
		else:
			try:
				response = request_prediction(
					os.getenv("PREDICTION_API_URL", DEFAULT_API_URL),
					build_payload(customer_id, features),
				)
				probability, bucket = extract_prediction(response)
				st.metric("Churn probability", f"{probability:.0%}")
				risk = bucket.removesuffix("_RISK")
				if bucket == "LOW_RISK":
					st.success(f"Churn Risk: {risk}")
				elif bucket == "MEDIUM_RISK":
					st.warning(f"Churn Risk: {risk}")
				else:
					st.error(f"Churn Risk: {risk}")
			except RuntimeError as exc:
				st.error(str(exc))
			except Exception:
				st.error("Something went wrong while requesting the prediction.")


if __name__ == "__main__":
	main()
