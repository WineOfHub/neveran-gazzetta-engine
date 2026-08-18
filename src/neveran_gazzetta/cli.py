from __future__ import annotations

import argparse
import json
import signal
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from neveran_gazzetta.application.contracts import JobLease
from neveran_gazzetta.runtime import build_live_runtime


def worker_main() -> None:
    parser = argparse.ArgumentParser(description="Worker autonomo Gazzetta")
    parser.add_argument("--once", action="store_true", help="Esegue un solo tick")
    args = parser.parse_args()
    runtime = build_live_runtime()
    if args.once:
        result = runtime.worker.tick()
        print(json.dumps({"status": result.status.value, "errorCode": result.error_code}))
        return

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_args: stop.set())
    signal.signal(signal.SIGINT, lambda *_args: stop.set())
    while not stop.is_set():
        runtime.worker.tick()
        stop.wait(runtime.config.runtime.worker.poll_seconds)


def api_main() -> None:
    import uvicorn

    from neveran_gazzetta.api.app import create_app

    runtime = build_live_runtime()
    token = runtime.config.secrets.api_token
    if token is None:
        raise RuntimeError("GAZZETTA_API_TOKEN obbligatorio")

    def ready() -> dict[str, object]:
        release_id = runtime.retrieval.active_release_id()
        runtime.control.get_editorial_state()
        return {"corpusReleaseId": release_id}

    app = create_app(
        service_token=token.get_secret_value(),
        worker=runtime.worker,
        status_provider=lambda: {
            "status": "online",
            "workerId": "neveranforge-gazzetta-1",
        },
        release_provider=lambda: {
            "corpusReleaseId": runtime.retrieval.active_release_id(),
        },
        ready_provider=ready,
        run_provider=runtime.control.get_run,
    )
    api = runtime.config.runtime.api
    uvicorn.run(app, host=api.host, port=api.port, access_log=False)


def canary_main() -> None:
    parser = argparse.ArgumentParser(description="Live eval senza pubblicazione")
    parser.add_argument("--confirm-live-no-publish", action="store_true", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    runtime = build_live_runtime()
    state = runtime.control.get_editorial_state()
    lease = JobLease(
        job_id=uuid4(),
        schedule_slot=datetime.now(UTC),
        attempt_number=1,
        policy_version=runtime.config.editorial.policy_version,
    )
    run = runtime.pipeline.execute(lease)
    target = args.output or Path("eval/live-results") / f"canary-{state.next_issue_number}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(run.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
    print(json.dumps({
        "published": False,
        "output": str(target),
        "validationStatus": run.validation_status.value,
        "tokens": run.token_input + run.token_output,
    }))


def preflight_main() -> None:
    parser = argparse.ArgumentParser(description="Preflight live strettamente read-only")
    parser.add_argument("--confirm-live-read-only", action="store_true", required=True)
    parser.parse_args()
    runtime = build_live_runtime()
    state = runtime.control.get_editorial_state()
    retrieval = runtime.retrieval.retrieve([
        "vita quotidiana commerci trasporti e cronache pubbliche di Neveran"
    ])
    available = runtime.generation_client.available_model_ids()
    generation = runtime.config.runtime.generation
    configured = {
        runtime.config.secrets.planner_model or generation.planner_model_default,
        runtime.config.secrets.writer_model or generation.writer_model_default,
        runtime.config.secrets.verifier_model or generation.verifier_model_default,
    }
    missing = sorted(configured - available)
    if missing:
        raise RuntimeError(f"Modelli Cloudflare non disponibili: {', '.join(missing)}")
    print(json.dumps({
        "writeOperations": 0,
        "corpusReleaseId": retrieval.corpus_release_id,
        "retrievedChunks": len(retrieval.chunks),
        "nextIssueNumber": state.next_issue_number,
        "models": sorted(configured),
    }))
