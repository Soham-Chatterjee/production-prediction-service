# Incident Report: Prediction API Concurrency Degradation

## Incident Summary

The prediction API was investigated after concurrency testing showed substantial latency growth as concurrent requests increased. The service initially completed all requests successfully, but throughput stopped scaling and tail latency increased significantly at higher concurrency. A later run with a shorter client timeout produced two `ReadTimeout` failures at concurrency 100.

The incident is best classified as a **performance and capacity issue**, not a correctness or data-loss incident.

### Current disposition

- **Reliability:** Healthy at the latest measured settings. The latest extended run completed all 18,050 requests successfully.
- **Performance:** Degraded at higher concurrency. Throughput peaks at lower concurrency and declines as concurrency increases.
- **Memory:** Stable during the observed test windows. No short-term memory leak was identified.
- **Root cause:** The measured delay is outside the prediction and route-stage execution measured by the service. The remaining bottleneck is in the end-to-end serving path, runtime, load-generation environment, or deployment configuration.
- **Code changes required:** No application-code performance fix is supported by the evidence. Worker configuration and other deployment-environment combinations are the primary ways to improve concurrency performance.

## Problem Being Investigated

The service must handle concurrent `POST /predict` requests while maintaining acceptable latency and throughput. The investigation aimed to answer:

1. How many concurrent requests can the service sustain?
2. At what concurrency does latency begin to rise sharply?
3. Does throughput continue to scale as concurrency increases?
4. Are failures caused by CPU or memory pressure?
5. Is the behavior caused by the prediction code or by the HTTP/server execution model?

The service was tested with concurrency levels from 1 through 100. Each level used repeated fixed-size batches, so the configured concurrency represented the number of requests active in a batch, while multiple batches provided enough observations for percentile calculations.

## Test Configuration

- Endpoint: `POST /predict`
- Client: asynchronous Python client using `httpx`
- Server: Uvicorn with four workers
- Request body: valid prediction payload with all eight required features
- Requests per level: 50 requests per batch across 50 batches
- Client timeout: extended beyond the initial 10-second setting
- Resource sampling: Python `psutil` monitor at 0.2-second intervals
- Process monitoring: Uvicorn master PID and descendant worker processes
- Latency: measured end to end by the load generator
- Throughput: completed requests divided by benchmark wall-clock duration

The benchmark implementation is in [benchmarks/load_test.py](../benchmarks/load_test.py).

## Diagnostic Instrumentation Implemented

To isolate the bottleneck before applying performance optimizations, the API now
adds diagnostic response headers without changing the JSON response contract:

- `X-Server-Total-Time-Ms`: total server-side request time measured by HTTP middleware.
- `X-Server-Engine-Lookup-Ms`: time to retrieve the engine from application state.
- `X-Server-Feature-Validation-Ms`: route-level required-feature check.
- `X-Server-Prediction-Ms`: time spent in `engine.predict`.
- `X-Server-Response-Creation-Ms`: time to construct the response model.

The benchmark reads these headers and reports the average and p95 for each
stage. Middleware timing includes request processing handled by the framework,
including parsing/validation and response handling, while route-level headers
cover only the stages executed inside the route. This makes the difference
between client-observed latency and server-side timing measurable.

This is diagnostic instrumentation, not yet a performance optimization. It is
covered by an integration test in [tests/integration/test_api.py](../tests/integration/test_api.py).

## Observed Results

| Concurrency | Requests | Successes | Failures | p50 (ms) | p95 (ms) | p99 (ms) | Throughput (req/s) |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 50 | 50 | 0 | 3.86 | 4.57 | 13.42 | 222.92 |
| 10 | 500 | 500 | 0 | 34.90 | 54.63 | 64.26 | 198.20 |
| 25 | 1,250 | 1,250 | 0 | 84.76 | 127.97 | 152.26 | 181.31 |
| 40 | 2,000 | 2,000 | 0 | 116.21 | 209.85 | 246.91 | 179.70 |
| 50 | 2,500 | 2,500 | 0 | 151.76 | 266.17 | 298.20 | 175.18 |
| 60 | 3,000 | 3,000 | 0 | 181.43 | 325.81 | 371.80 | 172.05 |
| 75 | 3,750 | 3,750 | 0 | 234.70 | 420.98 | 466.17 | 165.81 |
| 100 | 5,000 | 5,000 | 0 | 313.10 | 568.33 | 617.44 | 161.21 |

### Resource observations from the same run

| Concurrency | Average service CPU | Maximum service CPU | Average service memory | Maximum service memory | Maximum system CPU |
|---:|---:|---:|---:|---:|---:|
| 1 | 7.45% | 14.90% | 266.57 MB | 266.57 MB | 25.00% |
| 10 | 37.34% | 58.80% | 266.66 MB | 266.66 MB | 45.50% |
| 25 | 32.87% | 57.50% | 266.66 MB | 266.66 MB | 42.20% |
| 40 | 37.37% | 66.10% | 266.63 MB | 266.66 MB | 52.10% |
| 50 | 35.69% | 66.00% | 266.63 MB | 266.63 MB | 35.70% |
| 60 | 32.75% | 71.30% | 266.62 MB | 266.63 MB | 42.10% |
| 75 | 35.27% | 79.50% | 266.63 MB | 266.64 MB | 37.30% |
| 100 | 33.41% | 71.20% | 266.61 MB | 266.64 MB | 41.60% |

The resource monitor was corrected during the investigation to preserve `psutil` CPU baselines between samples and to aggregate the Uvicorn master and worker descendants. The service CPU values above are therefore more useful than the earlier all-zero readings.

### Server-stage timing observations

The instrumented run measured the following average and p95 server times in milliseconds:

| Concurrency | Server total avg/p95 | Prediction avg/p95 | Client p95 latency |
|---:|---:|---:|---:|
| 1 | 1.385 / 1.802 | 0.032 / 0.052 | 5.63 |
| 10 | 3.449 / 5.693 | 0.040 / 0.061 | 59.06 |
| 25 | 3.733 / 5.317 | 0.037 / 0.057 | 137.90 |
| 50 | 4.491 / 6.830 | 0.038 / 0.059 | 301.37 |
| 100 | 5.117 / 7.481 | 0.038 / 0.057 | 612.41 |

At concurrency 100, the application reports approximately 7.5 ms at p95,
while the client observes approximately 612.4 ms at p95. Prediction itself is
approximately 0.057 ms at p95. This measured gap shows that the prediction
algorithm and route-stage code are not the dominant source of end-to-end
latency.

## Discoveries

### 1. The service has a clear performance knee

Throughput is highest at low concurrency and begins to decline after approximately 10 to 25 concurrent requests. At concurrency 50, throughput is about 175 req/s. At concurrency 100, it falls to about 161 req/s while p99 latency rises to about 617 ms.

The practical operating point depends on the latency objective:

- For p99 below approximately 300 ms, concurrency 50 is near the limit.
- For p99 below approximately 500 ms, concurrency 75 is near the limit.
- Concurrency 100 exceeds both of those example targets.

These are capacity observations, not universal service-level objectives. The project should define the actual p95/p99 target before selecting a production limit.

### 2. Higher concurrency adds waiting time rather than useful capacity

Increasing concurrency from 50 to 100 does not double throughput. Instead, it approximately doubles p50 latency and increases p99 latency from 298 ms to 617 ms. This indicates that additional requests are spending more time waiting for available processing capacity or execution slots.

### 3. Memory is not the observed bottleneck

Service memory stayed close to 266.6 MB throughout the latest run. The maximum value was only marginally above the average at every concurrency level. This provides no evidence of a short-term memory leak or concurrency-driven unbounded allocation.

The measurement is resident memory for the monitored process tree and should still be repeated in the intended deployment environment, especially if every worker loads a separate model instance.

### 4. CPU is active but not continuously saturated

The service reached short CPU bursts up to approximately 79.5%, while average service CPU at concurrency 100 was approximately 33.4%. Whole-system CPU peaked at approximately 52.1%. This does not look like sustained total-machine CPU exhaustion.

The results are compatible with bursty work, scheduling overhead, process or thread contention, or a bottleneck elsewhere in the request path. CPU measurements alone do not identify which deployment component is responsible.

### 5. The initial CPU measurements were invalid

The first monitor implementation recreated `psutil.Process` objects for every sample and called `cpu_percent()` without retaining the prior baseline. That produced `0.00%` process CPU values. The monitor was subsequently corrected to cache process objects and initialize CPU sampling before collecting intervals.

This is a benchmark instrumentation correction, not an API-service fix.

### 6. The timeout run exposed tail behavior

An earlier run with a 10-second client timeout produced two `ReadTimeout` failures at concurrency 100. The later run with an extended timeout completed all requests, but this does not make the earlier observation irrelevant: it demonstrates that high concurrency can push requests beyond a client deadline under some conditions.

The benchmark calculates p50, p95, and p99 from successful requests only. Timed-out requests are reported as failures and are excluded from those latency percentiles, so a timeout run can understate the true worst-case end-to-end latency.

## Relationship to the Service Code

The relevant request path is the synchronous `predict` handler in [src/service/api/routes.py](../src/service/api/routes.py). It performs or triggers:

1. FastAPI/Pydantic request validation.
2. Retrieval of the shared engine from application state.
3. A required-feature set comparison.
4. Prediction-engine validation of required features again.
5. Logistic prediction calculation.
6. UUID generation and response model construction.
7. Response serialization and validation.

The route is declared with regular `def`, so FastAPI executes it using its synchronous execution mechanism rather than directly on the async event loop. Under load, available synchronous execution capacity and worker scheduling can contribute to queuing.

The actual prediction calculation in [src/engine/predict.py](../src/engine/predict.py) is small: it loops over eight features, performs scalar arithmetic, applies a logistic function, and records a timer. There is no evidence from the current data that the model arithmetic itself is expensive enough to explain the entire latency increase.

The server-stage measurements now provide stronger evidence than the initial
resource-only run. The route and prediction work remain nearly constant while
client latency grows by hundreds of milliseconds. Therefore, the most accurate
current conclusion is:

> Application-code changes to the prediction logic, validation, response construction, or route declaration will not solve the observed concurrency performance problem. The limiting behavior is outside the measured application stages and must be addressed through worker configuration, server/runtime settings, host environment, network/socket behavior, or load-generation configuration.

## Possible Code and Configuration Fixes

### Priority 1: Measure before changing behavior

Add separate timings around:

- Request parsing and validation.
- Engine lookup and feature checks.
- `engine.predict`.
- Response model construction and serialization.

Compare these timings with the load-test client latency. The engine already reports `processing_time_ms`, but that timer covers only the calculation portion and excludes most of the HTTP request path. A large difference between client latency and engine processing time would confirm that the main delay is outside model arithmetic.

Also add request-level metrics for queueing or in-flight requests if the production stack supports them.

### Priority 2: Do not pursue application-code optimization as the capacity fix

The route checks for missing feature keys, and the engine checks required features again. This duplication is small for eight features, and the measured feature-validation p95 is approximately `0.012 ms` at high concurrency. Removing it may improve code clarity, but it will not explain or resolve hundreds of milliseconds of client-observed latency.

Similarly, precomputing the expected feature set, changing the logistic calculation, caching metadata, or converting the synchronous route to `async def` is not expected to improve the observed concurrency behavior. The measured prediction p95 remains approximately `0.057 ms` at concurrency 100.

These changes should not be presented as remediation for this incident unless a future profile produces contrary evidence. Code cleanup remains possible, but it is out of scope for solving the current capacity limitation.

For correctness and maintainability, ownership can still be clarified:

- Let the request schema own shape/type validation.
- Let the route or engine own the domain-level required-feature check, but avoid performing the same check twice.

### Priority 3: Tune worker and deployment configuration

Do not change the handler to `async def` automatically. The prediction engine is synchronous; an async handler that directly calls it would execute CPU work on the event-loop thread and could make concurrency behavior worse.

The primary performance remediation is to test the serving environment with:

- Different Uvicorn worker counts.
- Different ASGI/server configurations.
- A controlled synchronous thread-pool capacity, if the deployment stack allows it.
- Different connection, keep-alive, backlog, and timeout settings where supported.
- A production-like host and network environment.

Compare worker counts and configuration combinations using identical request
loads. More workers may improve throughput and reduce queuing, but each worker
can consume additional memory and may introduce process-scheduling overhead.

If the prediction becomes materially more CPU-intensive in the future, consider explicitly moving model inference to a suitable worker pool or separate model-serving process rather than blocking the event loop.

### Priority 4: Improve deployment scaling

The test already improved when using four workers compared with the earlier single-worker result, but the latency knee remained. Test worker counts systematically and record memory per worker. More workers are not automatically better because each worker may load its own engine/model state and consume additional memory.

For production, a gateway-level concurrency limit or bounded queue can protect tail latency. The limit should be chosen from an agreed latency objective, not only from the maximum number of successful requests.

### Priority 5: Use code changes only for protection and observability

Code changes can still provide operational protection, such as a concurrency
limit, bounded queue, controlled `429 Too Many Requests` response, and metrics
or tracing. These measures can protect tail latency and make overload visible,
but they do not increase the service's underlying concurrency capacity.

## Recommended Remediation Plan

1. Define the service SLO, for example p95 and p99 latency targets plus an acceptable error rate.
2. Repeat the benchmark at the intended deployment location, with warm-up and multiple independent runs.
3. Compare one, two, and four Uvicorn workers using the same test settings.
4. Run the instrumented benchmark and compare internal request timings with client-observed latency.
5. Test deployment combinations involving worker count, ASGI server, host OS, connection settings, and network placement.
6. Run intermediate concurrency levels around the knee, such as 40, 50, 60, and 75.
7. Set an operational concurrency limit that keeps the selected percentile within the SLO.
8. Re-run the benchmark after every deployment change and compare throughput, p95, p99, failure rate, CPU, and memory.

## Final Assessment

The incident is real and reproducible: the prediction API remains correct and memory-stable, but its client-observed latency degrades and throughput stops scaling as concurrency increases. The latest run supports an initial operating limit around 40 to 50 concurrent requests when a p99 target near 300 ms is required.

The diagnostic timing evidence shows that application-code optimization will not
solve the observed concurrency performance problem. At concurrency 100, server
total p95 is approximately `7.481 ms`, prediction p95 is approximately
`0.057 ms`, and client p95 is approximately `612.41 ms`. The issue should
therefore be reported as a **deployment and serving-environment capacity
limitation**, rather than an algorithmic defect.

The primary remediation is to find a better worker/server/host configuration
combination and scale the deployment based on a measured SLO. Code changes may
still add bounded concurrency, overload responses, metrics, and tracing, but
those are safeguards and observability improvements, not fixes that increase
the underlying request-processing capacity.
