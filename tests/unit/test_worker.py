from __future__ import annotations

import threading
from datetime import UTC, datetime
from uuid import UUID, uuid4

from neveran_gazzetta.application.contracts import JobLease, PreparedRun
from neveran_gazzetta.worker.runner import GazzettaWorker, TickStatus


class Control:
    def __init__(self, lease: JobLease | None) -> None:
        self.lease = lease
        self.heartbeats: list[str] = []
        self.failed: list[dict[str, object]] = []
        self.published = False
        self.fail_job_raises = False

    def heartbeat(self, **kwargs) -> None:
        self.heartbeats.append(kwargs["status"])

    def lease_next(self, _worker_id: str) -> JobLease | None:
        return self.lease

    def renew_lease(self, _job_id: UUID, _worker_id: str) -> None:
        return None

    def submit_run(self, _lease, _worker_id, _run) -> UUID:
        return uuid4()

    def publish(self, _job_id, _worker_id, _run_id) -> dict[str, object]:
        self.published = True
        return {"schemaVersion": 1}

    def fail_job(self, **kwargs) -> None:
        if self.fail_job_raises:
            raise RuntimeError("stato già concluso")
        self.failed.append(kwargs)

    def maintain_retention(self, *_limits: int) -> int:
        return 0


class Pipeline:
    def __init__(self, status: str = "passed") -> None:
        self.status = status

    def execute(self, _lease: JobLease) -> PreparedRun:
        return PreparedRun(
            phase="publishing",
            validation_status=self.status,
            corpus_release_id="release-a",
            policy_hash="a" * 64,
            prompt_versions={
                "planner": "v1", "writer": "v1", "verifier": "v1", "repair": "v1",
            },
            prompt_hashes={key: "a" * 64 for key in ("planner", "writer", "verifier", "repair")},
            models={"planner": "model", "writer": "model", "verifier": "model"},
            token_input=0,
            token_output=0,
            groq_requests=0,
            snapshot={"schemaVersion": 1},
            content_hash="a" * 64,
        )


class BlockingPipeline(Pipeline):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def execute(self, lease: JobLease) -> PreparedRun:
        self.started.set()
        assert self.release.wait(timeout=2)
        return super().execute(lease)


def _lease() -> JobLease:
    return JobLease(
        job_id=uuid4(),
        schedule_slot=datetime.now(UTC),
        attempt_number=1,
        policy_version="v1",
    )


def _worker(control: Control, pipeline: Pipeline) -> GazzettaWorker:
    return GazzettaWorker(
        worker_id="worker-test",
        control=control,
        pipeline=pipeline,
        lease_renew_seconds=60,
        models={},
        hostname="test",
    )


def test_tick_senza_job_resta_idle() -> None:
    control = Control(None)

    result = _worker(control, Pipeline()).tick()

    assert result.status == TickStatus.IDLE
    assert control.heartbeats == ["online"]


def test_tick_pubblica_solo_run_validato() -> None:
    control = Control(_lease())

    result = _worker(control, Pipeline()).tick()

    assert result.status == TickStatus.PUBLISHED
    assert control.published
    assert not control.failed
    assert control.heartbeats == ["online", "busy", "online"]


def test_tick_rifiutato_non_pubblica_e_programma_retry_limitato() -> None:
    control = Control(_lease())

    result = _worker(control, Pipeline("rejected")).tick()

    assert result.status == TickStatus.FAILED
    assert result.error_code == "invalid_generation"
    assert not control.published
    assert control.failed[0]["retryable"] is True


def test_errore_di_rete_dopo_publish_non_nasconde_quello_originale() -> None:
    control = Control(_lease())
    control.fail_job_raises = True

    def lost_response(_job_id, _worker_id, _run_id):
        control.published = True
        raise RuntimeError("risposta persa")

    control.publish = lost_response  # type: ignore[method-assign]
    result = _worker(control, Pipeline()).tick()

    assert result.status == TickStatus.FAILED
    assert result.error_code == "unexpected_error"
    assert control.published


def test_due_tick_nello_stesso_processo_non_corrono_in_parallelo() -> None:
    control = Control(_lease())
    pipeline = BlockingPipeline()
    worker = _worker(control, pipeline)
    first_results = []
    first = threading.Thread(target=lambda: first_results.append(worker.tick()))
    first.start()
    assert pipeline.started.wait(timeout=1)

    second = worker.tick()
    pipeline.release.set()
    first.join(timeout=2)

    assert second.status == TickStatus.IDLE
    assert second.error_code == "tick_in_progress"
    assert first_results[0].status == TickStatus.PUBLISHED
