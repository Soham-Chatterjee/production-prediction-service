import asyncio
import argparse
import math
import time
import uuid
from collections import Counter
from dataclasses import dataclass

import httpx


PAYLOAD_FEATURES = {
	"credit_score": 650,
	"age": 45,
	"tenure": 3,
	"balance": 20000.0,
	"num_of_products": 1,
	"has_cr_card": 1,
	"is_active_member": 0,
	"estimated_salary": 50000.0,
}


@dataclass
class RequestResult:
	latency_ms: float
	status_code: int | None = None
	error: str | None = None


@dataclass
class BenchmarkResult:
	concurrency: int
	requests: int
	successes: int
	failures: int
	p50_ms: float | None
	p95_ms: float | None
	p99_ms: float | None
	throughput_rps: float
	failure_types: Counter[str]


def percentile(values: list[float], percentage: float) -> float | None:
	if not values:
		return None

	ordered = sorted(values)
	rank = (len(ordered) - 1) * percentage / 100
	lower = math.floor(rank)
	upper = math.ceil(rank)
	if lower == upper:
		return ordered[lower]
	weight = rank - lower
	return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


async def send_prediction(client: httpx.AsyncClient, endpoint: str) -> RequestResult:
	payload = {
		"request_id": str(uuid.uuid4()),
		"customer_id": "load-test-customer",
		"features": PAYLOAD_FEATURES,
	}
	started = time.perf_counter()
	try:
		response = await client.post(endpoint, json=payload)
		latency_ms = (time.perf_counter() - started) * 1000
		if response.status_code == 200:
			return RequestResult(latency_ms=latency_ms, status_code=200)
		return RequestResult(latency_ms=latency_ms, status_code=response.status_code)
	except Exception as error:
		latency_ms = (time.perf_counter() - started) * 1000
		return RequestResult(latency_ms=latency_ms, error=type(error).__name__)


async def run_benchmark(
	client: httpx.AsyncClient,
	endpoint: str,
	concurrency: int,
	batches: int,
) -> BenchmarkResult:
	results: list[RequestResult] = []
	started = time.perf_counter()

	for _ in range(batches):
		batch_results = await asyncio.gather(
			*(send_prediction(client, endpoint) for _ in range(concurrency))
		)
		results.extend(batch_results)

	elapsed_seconds = time.perf_counter() - started
	successful_latencies = [
		result.latency_ms for result in results if result.status_code == 200
	]
	failures = [result for result in results if result.status_code != 200]
	failure_types = Counter(
		str(result.status_code) if result.status_code is not None else result.error
		for result in failures
	)

	return BenchmarkResult(
		concurrency=concurrency,
		requests=len(results),
		successes=len(successful_latencies),
		failures=len(failures),
		p50_ms=percentile(successful_latencies, 50),
		p95_ms=percentile(successful_latencies, 95),
		p99_ms=percentile(successful_latencies, 99),
		throughput_rps=len(results) / elapsed_seconds if elapsed_seconds else 0,
		failure_types=failure_types,
	)


def format_metric(value: float | None) -> str:
	return f"{value:.2f}" if value is not None else "-"


def print_results(results: list[BenchmarkResult]) -> None:
	print(
		"concurrency | requests | successes | failures | "
		"p50_ms | p95_ms | p99_ms | throughput_rps"
	)
	for result in results:
		print(
			f"{result.concurrency:^11} | {result.requests:^8} | "
			f"{result.successes:^9} | {result.failures:^8} | "
			f"{format_metric(result.p50_ms):^6} | "
			f"{format_metric(result.p95_ms):^6} | "
			f"{format_metric(result.p99_ms):^6} | "
			f"{result.throughput_rps:^15.2f}"
		)
		if result.failure_types:
			print(f"  failures by type: {dict(result.failure_types)}")


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Run concurrent prediction requests.")
	parser.add_argument(
		"--endpoint",
		default="http://127.0.0.1:8000/predict",
		help="Prediction endpoint URL.",
	)
	parser.add_argument(
		"--batches",
		type=int,
		default=20,
		help="Number of batches for each concurrency level.",
	)
	parser.add_argument(
		"--timeout",
		type=float,
		default=10,
		help="Per-request timeout in seconds.",
	)
	return parser.parse_args()


async def main() -> None:
	args = parse_args()
	if args.batches < 1:
		raise ValueError("--batches must be at least 1")

	limits = httpx.Limits(max_connections=100, max_keepalive_connections=100)
	timeout = httpx.Timeout(args.timeout)
	async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
		results = [
			await run_benchmark(client, args.endpoint, concurrency, args.batches)
			for concurrency in (1, 10, 50, 100)
		]
	print_results(results)


if __name__ == "__main__":
	asyncio.run(main())
