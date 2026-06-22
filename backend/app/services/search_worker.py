"""Process-based search worker.

The worker function is intentionally defined in a dedicated module so it is
picklable by ``concurrent.futures.ProcessPoolExecutor`` on Windows (spawn).
"""

from __future__ import annotations

import asyncio


def run_search_job(job_id: str) -> None:
    """Load a persisted search job and run it to completion in a child process."""
    # Local imports keep the worker module light when it is only being pickled,
    # and avoid import side-effects in the parent process.
    import sys

    from app.services.search_jobs import SearchJobService

    print(f"[worker] starting job {job_id}", flush=True)
    service = SearchJobService()
    job = service.get_job(job_id)
    if job is None:
        print(f"[worker] job {job_id} not found", flush=True)
        return
    print(f"[worker] loaded job {job_id} with {len(job.sources)} sources", flush=True)
    asyncio.run(service.run_job(job_id))
    print(f"[worker] finished job {job_id}", flush=True)


def warm_search_worker() -> None:
    """Pre-import plugin modules in a worker process to amortize cold-start cost."""
    from app.services.search_jobs import SearchJobService

    service = SearchJobService()
    print(f"[worker] warmed with {len(service.scheduler._plugins)} plugins", flush=True)
