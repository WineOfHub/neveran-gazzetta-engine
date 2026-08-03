from __future__ import annotations

import json
import threading
from contextlib import suppress
from pathlib import Path
from typing import Protocol

import httpx

_SAFE_METADATA = {
    "attempt",
    "corpus_release_id",
    "error_code",
    "groq_requests",
    "job_id",
    "models",
    "policy_hash",
    "policy_version",
    "prompt_hashes",
    "prompt_versions",
    "rate_limits",
    "schedule_slot",
    "status",
    "token_input",
    "token_output",
    "worker_version",
}


class TelemetrySink(Protocol):
    def emit(
        self,
        event: str,
        *,
        status_code: int | None = None,
        duration_ms: int | None = None,
        provider: str | None = None,
        units: dict[str, int | str] | None = None,
        metadata: dict[str, object] | None = None,
        error_message: str | None = None,
        trace_id: str | None = None,
    ) -> None: ...


class NullTelemetry:
    def emit(
        self,
        _event: str,
        *,
        status_code: int | None = None,
        duration_ms: int | None = None,
        provider: str | None = None,
        units: dict[str, int | str] | None = None,
        metadata: dict[str, object] | None = None,
        error_message: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        return None


class MonitorTelemetry:
    """Invia batch singoli e conserva un buffer JSONL limitato se Monitor è offline."""

    def __init__(
        self,
        *,
        url: str,
        token: str,
        environment: str,
        buffer_path: Path,
        max_buffer_events: int = 500,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._environment = environment
        self._buffer_path = buffer_path
        self._max_buffer_events = max_buffer_events
        self._client = client or httpx.Client(timeout=5)
        self._lock = threading.Lock()

    def _safe_event(
        self,
        event: str,
        *,
        status_code: int | None,
        duration_ms: int | None,
        provider: str | None,
        units: dict[str, int | str] | None,
        metadata: dict[str, object] | None,
        error_message: str | None,
        trace_id: str | None,
    ) -> dict[str, object]:
        safe_metadata = {
            key: value for key, value in (metadata or {}).items() if key in _SAFE_METADATA
        }
        return {
            "service": "gazzetta-engine",
            "provider": provider,
            "endpoint": f"/engine/{event.strip('/')}",
            "method": "WORKER",
            "status_code": status_code,
            "duration_ms": duration_ms,
            "environment": self._environment,
            "trace_id": trace_id,
            "units": units,
            "error_message": error_message[:500] if error_message else None,
            "metadata": safe_metadata,
        }

    def _post(self, events: list[dict[str, object]]) -> None:
        for start in range(0, len(events), 200):
            response = self._client.post(
                f"{self._url}/v1/events",
                headers={"Authorization": f"Bearer {self._token}"},
                json={"events": events[start : start + 200]},
            )
            response.raise_for_status()

    def _read_buffer(self) -> list[dict[str, object]]:
        if not self._buffer_path.exists():
            return []
        rows: list[dict[str, object]] = []
        for line in self._buffer_path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
            except json.JSONDecodeError:
                continue
        return rows[-self._max_buffer_events :]

    def _write_buffer(self, events: list[dict[str, object]]) -> None:
        self._buffer_path.parent.mkdir(parents=True, exist_ok=True)
        retained = events[-self._max_buffer_events :]
        payload = "".join(
            json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
            for event in retained
        )
        self._buffer_path.write_text(payload, encoding="utf-8")

    def emit(
        self,
        event: str,
        *,
        status_code: int | None = None,
        duration_ms: int | None = None,
        provider: str | None = None,
        units: dict[str, int | str] | None = None,
        metadata: dict[str, object] | None = None,
        error_message: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        item = self._safe_event(
            event,
            status_code=status_code,
            duration_ms=duration_ms,
            provider=provider,
            units=units,
            metadata=metadata,
            error_message=error_message,
            trace_id=trace_id,
        )
        with self._lock:
            buffered = self._read_buffer()
            try:
                self._post([*buffered, item])
                if self._buffer_path.exists():
                    self._buffer_path.unlink()
            except (httpx.HTTPError, OSError, ValueError):
                with suppress(OSError):
                    self._write_buffer([*buffered, item])
