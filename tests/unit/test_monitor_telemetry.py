from pathlib import Path

import httpx

from neveran_gazzetta.telemetry import MonitorTelemetry


def test_monitor_offline_buffer_limitato_e_sanitizzato(tmp_path: Path) -> None:
    def offline(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    buffer_path = tmp_path / "monitor.jsonl"
    telemetry = MonitorTelemetry(
        url="https://monitor.example",
        token="segreto",
        environment="test",
        buffer_path=buffer_path,
        max_buffer_events=2,
        client=httpx.Client(transport=httpx.MockTransport(offline)),
    )
    for index in range(3):
        telemetry.emit(
            "job_failed",
            metadata={"job_id": str(index), "prompt": "NON DEVE USCIRE"},
        )

    rows = buffer_path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2
    assert "NON DEVE USCIRE" not in "".join(rows)
    assert "segreto" not in "".join(rows)


def test_monitor_flush_del_buffer_al_primo_successo(tmp_path: Path) -> None:
    buffer_path = tmp_path / "monitor.jsonl"
    responses = iter([httpx.Response(503), httpx.Response(202)])

    def transport(_request: httpx.Request) -> httpx.Response:
        return next(responses)

    telemetry = MonitorTelemetry(
        url="https://monitor.example",
        token="token",
        environment="test",
        buffer_path=buffer_path,
        client=httpx.Client(transport=httpx.MockTransport(transport)),
    )
    telemetry.emit("heartbeat")
    assert buffer_path.exists()
    telemetry.emit("scheduler_tick")
    assert not buffer_path.exists()
