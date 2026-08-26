# Production Prediction Service

A small FastAPI service that exposes a metadata-driven customer churn prediction API for customers associated with the banking industry. The current predictor uses a logistic function and coefficients stored in `src/engine/metadata.json`; it is intentionally structured so the calculation engine can later be replaced by a trained model without changing the external API contract.

## Architecture

```mermaid
flowchart LR
		Startup[Application startup]
		Lifespan[Lifespan context manager]
		Engine[PredictionEngine]
		Metadata[(metadata.json)]
		AppState[app.state.engine]
		Client[API client]
		App[FastAPI application]
		Validation[Pydantic request validation]
		Routes[API routes]
		Response[Pydantic response models]
		Error[Exception handlers]
		Frontend[Streamlit frontend]
		User[User]

		Startup --> Lifespan
		Lifespan --> Engine
		Engine --> Metadata
		Lifespan --> AppState
		User --> Frontend
		Frontend -->|HTTP JSON request| App
		Client --> App
		App --> Validation
		Validation -->|valid request| Routes
		Validation -->|invalid request| Error
		Routes --> AppState
		AppState --> Engine
		Engine --> Response
		Response --> App
		Routes -->|API or model error| Error
		Error --> App
		App --> Client
```

The same diagram is available on its own in [docs/architecture.md](docs/architecture.md).

At runtime, the request flow is:

1. Application startup triggers the FastAPI lifespan context manager.
2. The lifespan initializes the `PredictionEngine` and stores it in `app.state.engine`.
3. The engine loads and validates the local model metadata.
4. Requests arrive and FastAPI validates the top-level `PredictionRequest` fields.
5. The route retrieves the engine from `app.state.engine`.
6. The route verifies that every configured feature is present.
7. The engine calculates log odds, converts them to a probability, assigns a risk category, and records calculation time.
8. The route wraps the result in a `PredictionResponse`.

The repository also includes a Streamlit consumer in `src/frontend/app.py`.
It initializes the engine before rendering, collects the customer ID and all
required features, generates `request_id` with `uuid.uuid4()` on submission,
and calls the running `/predict` API. The user sees the churn probability as a
percentage and a color-coded `Churn Risk: LOW`, `MEDIUM`, or `HIGH` result;
request IDs, model metadata, and processing time remain technical details.

## Problem

Prediction consumer applications often need a stable service boundary around a model. They should not need to know how a model is loaded, which coefficients it uses, or how a raw score becomes a customer-facing risk category.

This service addresses that boundary for a churn-style prediction workflow:

- Accept customer identity and feature data through a JSON API.
- Validate required request information before prediction.
- Detect missing model features with a clear client error.
- Keep model metadata and coefficients outside the Python calculation code.
- Return a stable response containing the prediction, model identity, and processing time.
- Expose health and model metadata endpoints for operational checks.

The current implementation is a deterministic reference service with fail-fast model initialization. It is suitable for local development, API contract work, and model-serving experiments; it is not yet a production deployment of a trained ML artifact.

## Design

### Repository layout

```text
src/
	engine/
		metadata.json       Model identity, feature definitions, and weights
		predict.py          PredictionEngine and scoring logic
	schemas/
		requests.py         Incoming request models
		responses.py        HTTP response models
		models.py           Internal model metadata and prediction models
		exceptions.py       Domain and API exceptions
	service/
		main.py             FastAPI application and exception handlers
		api/
			dependencies.py   PredictionEngine dependency factory
			routes.py         /health, /model, and /predict routes
	frontend/
		app.py             Streamlit prediction client
tests/
	unit/                 Engine, schema, and dependency tests
	integration/          HTTP API and frontend/API contract tests
docs/
	architecture.md      Standalone Mermaid architecture diagram
```

### Prediction calculation

The engine starts with the metadata intercept and adds each feature multiplied by its configured weight:

$$
z = b + \sum_{i=1}^{n} w_i x_i
$$

It then applies the logistic function and rounds the result to two decimal places:

$$
P(\text{churn}) = \frac{1}{1 + e^{-z}}
$$

The category thresholds are:

| Probability | Category |
| --- | --- |
| `< 0.33` | `LOW_RISK` |
| `0.33` to `< 0.67` | `MEDIUM_RISK` |
| `>= 0.67` | `HIGH_RISK` |

### Separation of concerns

- `PredictionEngine` owns metadata loading and prediction math.
- FastAPI lifespan manages engine initialization at application startup.
- Route handlers own HTTP request and response composition, accessing the engine from `app.state`.
- The Streamlit frontend owns user input, client-side validation, API calls, and user-friendly result/error presentation.
- Pydantic models define the public data shape.
- Exception handlers translate known failures into HTTP responses.
- The metadata file keeps model identity, feature documentation, and weights configurable without changing scoring code.

## API

The application listens on port `8000` when started with the command shown in the Configuration section. FastAPI also exposes interactive documentation at `/docs` and `/redoc`.

### `GET /health`

Returns service availability and the API version.

```json
{
	"status": "healthy",
	"api_version": "1.0.0"
}
```

Response code: `200 OK`.

### `GET /model`

Returns the public identity of the loaded model, without exposing feature weights.

```json
{
	"model_name": "mock-churn-predictor",
	"model_version": "v1.0",
	"num_features": 8,
	"model_type": "logistic_regression"
}
```

Response codes:

- `200 OK` when metadata loads successfully.
- `500 Internal Server Error` when model initialization fails.

### `POST /predict`

Request body:

```json
{
	"request_id": "request-123",
	"customer_id": "customer-123",
	"features": {
		"credit_score": 650,
		"age": 45,
		"tenure": 3,
		"balance": 20000.0,
		"num_of_products": 1,
		"has_cr_card": 1,
		"is_active_member": 0,
		"estimated_salary": 50000.0
	}
}
```

Required feature keys are:

`credit_score`, `age`, `tenure`, `balance`, `num_of_products`, `has_cr_card`, `is_active_member`, and `estimated_salary`.

Successful response:

```json
{
	"response_id": "generated-uuid",
	"request_id": "request-123",
	"prediction": {
		"churn_probability": 0.7,
		"prediction": "HIGH_RISK"
	},
	"model": {
		"name": "mock-churn-predictor",
		"version": "v1.0"
	},
	"metadata": {
		"processing_time_ms": 0.01
	}
}
```

The Streamlit frontend generates `request_id` automatically for each
submission; users enter only the `customer_id` and feature values. It formats
`churn_probability` as a percentage and displays the bucket as `Churn Risk`:
`LOW` (green), `MEDIUM` (amber), or `HIGH` (red).

Response codes:

| Code | Meaning |
| --- | --- |
| `200` | Prediction created successfully |
| `422` | Missing or invalid top-level request information |
| `422` | Missing required feature, for example `Missing required features: age` |
| `500` | Unexpected prediction or model failure |

Example request with `curl`:

```powershell
curl.exe -X POST http://127.0.0.1:8000/predict `
	-H "Content-Type: application/json" `
	-d '{"request_id":"request-123","customer_id":"customer-123","features":{"credit_score":650,"age":45,"tenure":3,"balance":20000.0,"num_of_products":1,"has_cr_card":1,"is_active_member":0,"estimated_salary":50000.0}}'
```

## Configuration

### Prerequisites

- Python `3.10` or newer.
- `uv` installed and available on `PATH`.

### Install dependencies

From the repository root:

```powershell
uv sync --extra dev
```

The project dependencies are declared in `pyproject.toml`. `uv.lock` pins the resolved dependency graph.

### Start the service

```powershell
uv run uvicorn src.service.main:app --reload
```

For a non-reloading local process:

```powershell
uv run uvicorn src.service.main:app --host 0.0.0.0 --port 8000
```

### Start the Streamlit frontend

Start the API first, then run the frontend from the repository root:

```powershell
uv run streamlit run src/frontend/app.py
```

The frontend validates the prediction engine during startup and stops with a
user-friendly error if the model metadata cannot be loaded. It sends requests
to `http://127.0.0.1:8000` by default; set `PREDICTION_API_URL` to use another
API address.

The API and frontend are separate processes. Start the API before submitting
a prediction from the frontend.

### Model metadata

The engine reads `src/engine/metadata.json` at initialization. The file must contain these top-level fields:

- `model_name`
- `model_version`
- `num_features`
- `model_type`
- `features`
- `weights`

The `weights` object contains `intercept` and the coefficients used by the engine. The `features` object documents the expected feature keys and is also used by the API route to detect missing inputs.

The engine loads metadata once at application startup via the FastAPI lifespan context manager. If metadata is invalid, the application fails to start. This ensures that either the service is fully operational with a valid model, or it fails immediately rather than later during a request.

## Testing

Install development dependencies and run the complete suite:

```powershell
uv sync --extra dev
uv run pytest -q
```

Run only unit tests:

```powershell
uv run pytest tests/unit -q
```

Run only integration tests:

```powershell
uv run pytest tests/integration -q
```

Show `print()` output from tests:

```powershell
uv run pytest tests/integration -s -q
```

The test suite covers:

- Metadata loading and invalid metadata.
- Log-odds and probability calculations.
- All three risk categories.
- Missing feature detection.
- Request and response schema requirements.
- Dependency error translation.
- Health, model, and prediction endpoints.
- Streamlit payload construction, API response extraction, API failures, and frontend engine initialization failures.
- HTTP `404`, `422`, and `500` behavior.

## Failure Handling

Known failures are translated at the HTTP boundary:

| Failure | Handler | Status | Response |
| --- | --- | --- | --- |
| Missing top-level request field | FastAPI `RequestValidationError` handler | `422` | `Missing required information in payload: customer_id` |
| Missing feature | `InvalidRequest` handler | `422` | `Missing required features: age` |
| Invalid model initialization | `ModelInitializationError` handler | `500` | `Failed to initialize the prediction engine` |
| Unexpected route failure | `UnknownAPIException` handler | `500` | `An unexpected error occurred` |
| Unknown route | FastAPI default handler | `404` | `Not Found` |

The service deliberately avoids returning model internals in generic `500` responses. Detailed exception context remains available in the server process for logging, but the current application does not yet configure structured logging or centralized error reporting.

The Streamlit frontend translates connection failures, API error responses,
malformed API responses, and unexpected request failures into concise messages
without exposing technical exception details. Its startup check also prevents
the UI from rendering when the local engine cannot initialize.

One important operational distinction is that Pydantic request validation happens before the route function runs. Missing `customer_id` therefore uses the `RequestValidationError` handler, while a missing key inside the free-form `features` dictionary is detected by the prediction route.

## Performance

The engine measures only the scoring section with `time.perf_counter()` and returns the elapsed duration as `metadata.processing_time_ms`. This value does not include all network, JSON parsing, dependency, metadata-loading, or response-serialization time.

The current scoring operation is $O(n)$ in the number of configured features and uses constant-size in-memory metadata after initialization. The arithmetic itself is lightweight; in a deployed service, the dominant latency is more likely to come from process startup, dependency construction, request handling, network overhead, logging, or a future model runtime.

Performance work should measure the complete request lifecycle, not only the engine timer. At minimum, collect request count, success and error counts, latency percentiles such as p50, p95, and p99, and resource utilization. Measurements should be separated by endpoint and status code, and should include realistic payload sizes and concurrency.

## Concurrency Benchmark

The service was tested with increasing concurrent request loads.

| Concurrency | Requests | Successes | Failures | p50 (ms) | p95 (ms) | p99 (ms) | Throughput (RPS) |
|------------:|---------:|----------:|---------:|---------:|---------:|---------:|-----------------:|
| 1           | 20       | 20        | 0        | 4.19     | 5.67     | 19.61    | 189.07           |
| 10          | 200      | 200       | 0        | 40.90    | 65.91    | 75.53    | 164.98           |
| 50          | 1,000    | 1,000     | 0        | 158.91   | 277.47   | 305.37   | 166.86           |
| 100         | 2,000    | 2,000     | 0        | 343.22   | 616.64   | 675.92   | 148.68           |

### Observations:

- No request failures were observed.
- Latency increased significantly with concurrency.
- Throughput plateaued around ~150–170 RPS.
- p99 latency increased substantially under high concurrency.
- Further investigation is required to identify the limiting resource.

### Investigation summary

The initial benchmark showed a reproducible capacity limitation: throughput
stopped scaling while p95 and p99 latency increased sharply, especially at 100
concurrent requests. Resource monitoring showed stable memory and no sustained
system-wide CPU exhaustion.

To isolate the source, the benchmark was extended to monitor Uvicorn workers and
the API was instrumented with server-stage timing headers. At concurrency 100,
the prediction stage took approximately `0.057 ms` at p95 and total server time
was approximately `7.481 ms` at p95, while client-observed p95 latency was
approximately `612.41 ms`. This indicates that the prediction algorithm and
measured application stages are not the dominant source of the concurrency
latency.

No application-code change is currently supported as a fix for increasing
concurrency performance. The primary remediation path is to evaluate worker
counts, ASGI server settings, connection configuration, host/runtime, and
network placement. Code changes may still provide safeguards such as bounded
concurrency, overload responses, metrics, and tracing, but these do not increase
the underlying capacity.

See the complete [concurrency degradation incident report](docs/incident-report-concurrency.md)
for the investigation evidence, conclusions, and remediation plan.

## Incident Analysis

The following incidents were identified and resolved during development:

### Import failures during test execution

Running the test file directly caused `ImportError: attempted relative import with no known parent package`. Switching tests to absolute `src` imports and ensuring the repository root is available on `sys.path` resolved the package-context problem.

Running under a system interpreter then caused `ModuleNotFoundError: No module named 'src'` or missing dependencies depending on the working directory. The supported invocation is from the repository root with `uv run`, and `tests/conftest.py` provides test discovery path setup.

### Pydantic model passed as JSON

Passing a `PredictionRequest` object directly as the HTTP client's `json` value caused a serialization error. Tests now send `request.model_dump()` so the client receives a plain dictionary.

### Missing prediction timing field

`ModelPrediction` requires `processing_time_ms`. The engine now measures its calculation and supplies that field before the response is built.

### Inconsistent client error messages

Top-level missing fields and missing nested features follow different validation paths. Explicit handlers and route checks now provide distinct, stable messages so clients can tell whether request information or a model feature is missing.

For future incidents, capture the request correlation identifier (`request_id`), endpoint, response code, latency, exception class, model version, and deployment version. Do not log sensitive customer data or full feature payloads by default.

## Design Decisions

- **FastAPI:** Provides typed request parsing, OpenAPI documentation, a lightweight HTTP layer, and a lifespan context manager for application startup/shutdown.
- **Pydantic models:** Make required top-level fields explicit and produce consistent validation behavior.
- **JSON metadata:** Keeps the example model inspectable and easy to replace while avoiding a database or model registry dependency.
- **Lifespan-initialized engine:** The engine is created once at application startup and stored in `app.state`. This ensures the service either starts fully operational or fails immediately. Routes access the pre-initialized engine from app state, making them lightweight and testable.
- **Stable response envelope:** Separates prediction values, model identity, and timing metadata so consumers can evolve independently.
- **Custom exception handlers:** Prevent implementation details from leaking into client responses and provide predictable status codes.
- **Separate unit and integration tests:** Unit tests isolate model behavior; integration tests verify the complete HTTP contract.
- **`uv` workflow:** Provides reproducible dependency resolution and a single command for running the service and tests.

## Limitations

- The current predictor is a hand-configured reference calculation, not a trained or persisted ML model.
- Feature values are stored in a plain `dict`, so the API does not enforce per-feature types, ranges, units, or domain constraints.
- The engine has a hard-coded required-feature list that can drift from the feature definitions in metadata.
- Model metadata is loaded from the local filesystem and is not versioned or fetched from a model registry at runtime.
- There is no authentication, authorization, rate limiting, request size policy, or abuse protection.
- There is no persistence, batch prediction endpoint, asynchronous job workflow, or request queue.
- There is no structured logging, metrics exporter, tracing, alerting, or explicit health distinction between process availability and model readiness. The API has a `/health` endpoint and fail-fast startup, while the frontend separately validates its local engine at startup.
- Processing time measures only the arithmetic block, so it should not be treated as end-to-end latency.
- API error handling returns generic `500` responses for unexpected failures and does not expose a machine-readable error code. The frontend provides user-friendly translations, but it does not replace the API error contract.
- The test suite does not include load tests, contract tests against deployed infrastructure, security tests, UI/browser automation, or model-quality evaluation.

## Future Improvements

### Model serving

- Plug in an actual trained ML model with a defined serialization format and compatibility contract.
- Load models through a model registry or artifact store with checksums, staged rollouts, and rollback support.
- Validate model and feature schema compatibility at startup.
- Keep the frontend feature controls and API validation generated from one authoritative schema, including types, ranges, and units.
- Add model-quality metrics such as precision, recall, ROC-AUC, calibration, drift, and segment-level performance.

### Throughput and latency

- Benchmark request bottlenecks across parsing, model inference, serialization, and network layers.
- Add load and stress tests with realistic concurrency and payload distributions.
- Measure and publish p50, p95, p99, maximum latency, throughput, error rate, and saturation signals.
- Profile CPU and memory use, then tune worker counts, connection limits, payload handling, and model execution.
- Batch compatible requests where the selected model benefits from vectorized inference.

### Asynchronous and batch workflows

- Enable asynchronous request handling where model and downstream I/O make it beneficial.
- Add a queue-backed asynchronous prediction endpoint for long-running inference.
- Return a job identifier and provide status and result endpoints.
- Support batch prediction with bounded payload sizes and partial-failure reporting.

### Reliability and operations

- Add structured logs, distributed tracing, Prometheus-compatible metrics, and alerts.
- Separate liveness, readiness, and model-readiness checks.
- Add graceful shutdown, timeouts, retries where appropriate, and concurrency limits.
- Add authentication, authorization, rate limiting, redaction, and audit logging.
- Introduce canary deployment, model rollback, and configuration validation in CI/CD.

### Maintainability

- Generate feature validation models from the metadata schema or define one authoritative schema.
- Replace generic dictionaries with typed feature and response models.
- Add an explicit API error schema with stable error codes and request identifiers.
- Add OpenAPI contract checks and deployment smoke tests.