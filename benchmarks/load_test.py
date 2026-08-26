import asyncio
import argparse
import math
import time
import uuid
from collections import Counter
from dataclasses import dataclass

import httpx
import psutil


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
	server_timings: dict[str, float] | None = None


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
	average_cpu_percent: float
	maximum_cpu_percent: float
	average_memory_mb: float
	maximum_memory_mb: float
	average_system_cpu_percent: float
	maximum_system_cpu_percent: float
	average_system_memory_percent: float
	maximum_system_memory_percent: float
	timing_summary: dict[str, tuple[float, float]]


@dataclass
class ResourceSample:
	cpu_percent: float
	memory_mb: float
	system_cpu_percent: float
	system_memory_percent: float


class ResourceMonitor:
	def __init__(self, process_id: int | None, interval_seconds: float) -> None:
		self.process_id = process_id
		self.interval_seconds = interval_seconds
		self.samples: list[ResourceSample] = []
		self._process_cache: dict[int, psutil.Process] = {}
		self._stop_event = asyncio.Event()

	def _processes(self) -> list[psutil.Process]:
		if self.process_id is None:
			return []
		try:
			root = psutil.Process(self.process_id)
			processes = [root, *root.children(recursive=True)]
			current_pids = {process.pid for process in processes}
			self._process_cache = {
				pid: process
				for pid, process in self._process_cache.items()
				if pid in current_pids
			}
			for process in processes:
				self._process_cache.setdefault(process.pid, process)
			return list(self._process_cache.values())
		except (psutil.NoSuchProcess, psutil.AccessDenied):
			return []

	def _sample(self) -> ResourceSample:
		processes = self._processes()
		cpu_percent = 0.0
		memory_bytes = 0
		for process in processes:
			try:
				cpu_percent += process.cpu_percent()
				memory_bytes += process.memory_info().rss
			except (psutil.NoSuchProcess, psutil.AccessDenied):
				continue

		return ResourceSample(
			cpu_percent=cpu_percent,
			memory_mb=memory_bytes / (1024 * 1024),
			system_cpu_percent=psutil.cpu_percent(),
			system_memory_percent=psutil.virtual_memory().percent,
		)

	async def collect(self) -> None:
		psutil.cpu_percent()
		for process in self._processes():
			try:
				process.cpu_percent()
			except (psutil.NoSuchProcess, psutil.AccessDenied):
				continue

		while True:
			try:
				await asyncio.wait_for(
					self._stop_event.wait(), timeout=self.interval_seconds
				)
				self.samples.append(self._sample())
				return
			except asyncio.TimeoutError:
				self.samples.append(self._sample())

	def stop(self) -> None:
		self._stop_event.set()

	def summary(self) -> dict[str, float]:
		if not self.samples:
			return {
				"average_cpu_percent": 0.0,
				"maximum_cpu_percent": 0.0,
				"average_memory_mb": 0.0,
				"maximum_memory_mb": 0.0,
				"average_system_cpu_percent": 0.0,
				"maximum_system_cpu_percent": 0.0,
				"average_system_memory_percent": 0.0,
				"maximum_system_memory_percent": 0.0,
			}

		return {
			"average_cpu_percent": sum(sample.cpu_percent for sample in self.samples) / len(self.samples),
			"maximum_cpu_percent": max(sample.cpu_percent for sample in self.samples),
			"average_memory_mb": sum(sample.memory_mb for sample in self.samples) / len(self.samples),
			"maximum_memory_mb": max(sample.memory_mb for sample in self.samples),
			"average_system_cpu_percent": sum(sample.system_cpu_percent for sample in self.samples) / len(self.samples),
			"maximum_system_cpu_percent": max(sample.system_cpu_percent for sample in self.samples),
			"average_system_memory_percent": sum(sample.system_memory_percent for sample in self.samples) / len(self.samples),
			"maximum_system_memory_percent": max(sample.system_memory_percent for sample in self.samples),
		}


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
		server_timings = {
			name: float(response.headers[header])
			for name, header in {
				"total": "X-Server-Total-Time-Ms",
				"engine_lookup": "X-Server-Engine-Lookup-Ms",
				"feature_validation": "X-Server-Feature-Validation-Ms",
				"prediction": "X-Server-Prediction-Ms",
				"response_creation": "X-Server-Response-Creation-Ms",
			}.items()
			if header in response.headers
		}
		if response.status_code == 200:
			return RequestResult(
				latency_ms=latency_ms,
				status_code=200,
				server_timings=server_timings,
			)
		return RequestResult(
			latency_ms=latency_ms,
			status_code=response.status_code,
			server_timings=server_timings,
		)
	except Exception as error:
		latency_ms = (time.perf_counter() - started) * 1000
		return RequestResult(latency_ms=latency_ms, error=type(error).__name__)


async def run_benchmark(
	client: httpx.AsyncClient,
	endpoint: str,
	concurrency: int,
	batches: int,
	process_id: int | None,
	sample_interval: float,
) -> BenchmarkResult:
	results: list[RequestResult] = []
	started = time.perf_counter()
	monitor = ResourceMonitor(process_id, sample_interval)
	monitor_task = asyncio.create_task(monitor.collect())

	try:
		for _ in range(batches):
			batch_results = await asyncio.gather(
				*(send_prediction(client, endpoint) for _ in range(concurrency))
			)
			results.extend(batch_results)
	finally:
		elapsed_seconds = time.perf_counter() - started
		monitor.stop()
		await monitor_task

	successful_latencies = [
		result.latency_ms for result in results if result.status_code == 200
	]
	failures = [result for result in results if result.status_code != 200]
	failure_types = Counter(
		str(result.status_code) if result.status_code is not None else result.error
		for result in failures
	)
	resource_summary = monitor.summary()
	timing_summary = {}
	for timing_name in ("total", "engine_lookup", "feature_validation", "prediction", "response_creation"):
		timings = [
			result.server_timings[timing_name]
			for result in results
			if result.server_timings and timing_name in result.server_timings
		]
		if timings:
			timing_summary[timing_name] = (
				sum(timings) / len(timings),
				percentile(timings, 95) or 0.0,
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
		**resource_summary,
		timing_summary=timing_summary,
	)


def format_metric(value: float | None) -> str:
	return f"{value:.2f}" if value is not None else "-"


def print_results(results: list[BenchmarkResult]) -> None:
	print(
		"concurrency | requests | successes | failures | "
		"p50_ms | p95_ms | p99_ms | throughput_rps | "
		"avg_cpu_% | max_cpu_% | avg_mem_mb | max_mem_mb"
	)
	for result in results:
		print(
			f"{result.concurrency:^11} | {result.requests:^8} | "
			f"{result.successes:^9} | {result.failures:^8} | "
			f"{format_metric(result.p50_ms):^6} | "
			f"{format_metric(result.p95_ms):^6} | "
			f"{format_metric(result.p99_ms):^6} | "
			f"{result.throughput_rps:^15.2f} | "
			f"{result.average_cpu_percent:^10.2f} | "
			f"{result.maximum_cpu_percent:^10.2f} | "
			f"{result.average_memory_mb:^11.2f} | "
			f"{result.maximum_memory_mb:^11.2f}"
		)
		print(
			f"  system cpu avg/max: {result.average_system_cpu_percent:.2f}% / "
			f"{result.maximum_system_cpu_percent:.2f}%; "
			f"system memory avg/max: {result.average_system_memory_percent:.2f}% / "
			f"{result.maximum_system_memory_percent:.2f}%"
		)
		if result.failure_types:
			print(f"  failures by type: {dict(result.failure_types)}")
		if result.timing_summary:
			print(
				"  server timing avg/p95 ms: "
				+ ", ".join(
					f"{name}={average:.3f}/{p95:.3f}"
					for name, (average, p95) in result.timing_summary.items()
				)
			)


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
	parser.add_argument(
		"--pid",
		type=int,
		help="Uvicorn master PID; includes all child worker processes in resource metrics.",
	)
	parser.add_argument(
		"--sample-interval",
		type=float,
		default=1.0,
		help="Resource sampling interval in seconds.",
	)
	return parser.parse_args()


async def main() -> None:
	args = parse_args()
	if args.batches < 1:
		raise ValueError("--batches must be at least 1")
	if args.sample_interval <= 0:
		raise ValueError("--sample-interval must be greater than 0")

	limits = httpx.Limits(max_connections=100, max_keepalive_connections=100)
	timeout = httpx.Timeout(args.timeout)
	async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
		results = [
			await run_benchmark(
				client,
				args.endpoint,
				concurrency,
				args.batches,
				args.pid,
				args.sample_interval,
			)
			for concurrency in (1, 10, 25, 40, 50, 60, 75, 100)
		]
	print_results(results)


if __name__ == "__main__":
	asyncio.run(main())
