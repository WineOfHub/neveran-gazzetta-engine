from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from neveran_gazzetta.domain.errors import (
    ConfigurationError,
    InvalidGeneration,
    ProviderAuth,
    ProviderQuota,
    ProviderUnavailable,
)
from neveran_gazzetta.generation.codex_cli import CodexCliJsonClient
from neveran_gazzetta.generation.models import GroqJsonResult

SCHEMA = {"type": "object", "properties": {"premise": {"type": "string"}}}


class FakeRunner:
    """Sostituisce _default_runner: mai un vero sottoprocesso nei test unit.
    `on_call` riceve (cmd, kwargs) e decide cosa fare — scrivere il file di
    output atteso da -o, sollevare TimeoutExpired, ecc."""

    def __init__(self, on_call) -> None:
        self._on_call = on_call
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, cmd, *, input="", timeout=None, env=None, cwd=None):
        self.calls.append((cmd, {"input": input, "timeout": timeout, "env": env, "cwd": cwd}))
        return self._on_call(cmd, input=input, timeout=timeout, env=env, cwd=cwd)


def _output_path(cmd: list[str]) -> Path:
    return Path(cmd[cmd.index("-o") + 1])


def _schema_path(cmd: list[str]) -> Path:
    return Path(cmd[cmd.index("--output-schema") + 1])


TURN_COMPLETED = json.dumps({
    "type": "turn.completed",
    "usage": {"input_tokens": 120, "output_tokens": 340},
})


def _client(runner) -> CodexCliJsonClient:
    return CodexCliJsonClient(
        executable="codex", sandbox="read-only", timeout_seconds=60,
        auth_recheck_seconds=300, quota_cooldown_seconds=1800,
        reasoning_effort="medium", runner=runner,
    )


def _call(client: CodexCliJsonClient) -> GroqJsonResult:
    return client.complete_json(
        model="gpt-5.6-sol", system_prompt="scrivi", user_payload={"foo": "bar"},
        schema_name="edition", schema=SCHEMA, max_tokens=4000, strict=True,
    )


def test_percorso_felice_ritorna_payload_e_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    def on_call(cmd, **_kw):
        _output_path(cmd).write_text(json.dumps({"premise": "ok"}), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, TURN_COMPLETED, "")

    runner = FakeRunner(on_call)
    monkeypatch.setattr("shutil.which", lambda _exe: "/usr/bin/codex")
    result = _call(_client(runner))

    assert result.payload == {"premise": "ok"}
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 340
    assert result.rate_limits == {}


def test_schema_scritto_su_file_temporaneo_e_ripulito(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Path] = {}

    def on_call(cmd, **_kw):
        path = _schema_path(cmd)
        seen["schema_path"] = path
        seen["schema_content"] = json.loads(path.read_text(encoding="utf-8"))
        _output_path(cmd).write_text(json.dumps({"premise": "ok"}), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, TURN_COMPLETED, "")

    runner = FakeRunner(on_call)
    monkeypatch.setattr("shutil.which", lambda _exe: "/usr/bin/codex")
    _call(_client(runner))

    assert seen["schema_content"]["additionalProperties"] is False
    assert not seen["schema_path"].exists()  # tempdir ripulita nel finally


def test_marker_auth_diventa_provider_auth_con_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    def on_call(cmd, **_kw):
        return subprocess.CompletedProcess(cmd, 1, "", "Error: not authenticated, run codex login")

    runner = FakeRunner(on_call)
    monkeypatch.setattr("shutil.which", lambda _exe: "/usr/bin/codex")
    with pytest.raises(ProviderAuth) as exc_info:
        _call(_client(runner))
    assert exc_info.value.retry_after_seconds == 300


def test_marker_quota_diventa_provider_quota_con_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    def on_call(cmd, **_kw):
        return subprocess.CompletedProcess(cmd, 1, "", "429 Too Many Requests: rate limit exceeded")

    runner = FakeRunner(on_call)
    monkeypatch.setattr("shutil.which", lambda _exe: "/usr/bin/codex")
    with pytest.raises(ProviderQuota) as exc_info:
        _call(_client(runner))
    assert exc_info.value.retry_after_seconds == 1800


def test_uscita_non_zero_senza_marker_diventa_invalid_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def on_call(cmd, **_kw):
        return subprocess.CompletedProcess(cmd, 2, "", "errore generico")

    runner = FakeRunner(on_call)
    monkeypatch.setattr("shutil.which", lambda _exe: "/usr/bin/codex")
    with pytest.raises(InvalidGeneration):
        _call(_client(runner))


def test_file_di_output_assente_diventa_invalid_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    def on_call(cmd, **_kw):
        return subprocess.CompletedProcess(cmd, 0, TURN_COMPLETED, "")  # -o mai scritto

    runner = FakeRunner(on_call)
    monkeypatch.setattr("shutil.which", lambda _exe: "/usr/bin/codex")
    with pytest.raises(InvalidGeneration):
        _call(_client(runner))


def test_output_non_json_diventa_invalid_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    def on_call(cmd, **_kw):
        _output_path(cmd).write_text("questo non e' json {{{", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, TURN_COMPLETED, "")

    runner = FakeRunner(on_call)
    monkeypatch.setattr("shutil.which", lambda _exe: "/usr/bin/codex")
    with pytest.raises(InvalidGeneration):
        _call(_client(runner))


def test_usage_assente_diventa_invalid_generation_non_zero_silenzioso(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def on_call(cmd, **_kw):
        _output_path(cmd).write_text(json.dumps({"premise": "ok"}), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")  # nessun evento turn.completed

    runner = FakeRunner(on_call)
    monkeypatch.setattr("shutil.which", lambda _exe: "/usr/bin/codex")
    with pytest.raises(InvalidGeneration):
        _call(_client(runner))


def test_chiavi_env_vietate_rimosse_dal_sottoprocesso(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_env: dict[str, str] = {}

    def on_call(cmd, *, env=None, **_kw):
        captured_env.update(env or {})
        _output_path(cmd).write_text(json.dumps({"premise": "ok"}), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, TURN_COMPLETED, "")

    runner = FakeRunner(on_call)
    monkeypatch.setattr("shutil.which", lambda _exe: "/usr/bin/codex")
    monkeypatch.setenv("OPENAI_API_KEY", "should-not-leak")
    monkeypatch.setenv("CODEX_API_KEY", "should-not-leak-either")
    _call(_client(runner))

    assert "OPENAI_API_KEY" not in captured_env
    assert "CODEX_API_KEY" not in captured_env


def test_eseguibile_assente_diventa_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def never_called(cmd, **_kw):
        raise AssertionError("mai chiamato")

    monkeypatch.setattr("shutil.which", lambda _exe: None)
    with pytest.raises(ConfigurationError):
        _call(_client(FakeRunner(never_called)))


def test_timeout_diventa_provider_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def on_call(cmd, **_kw):
        raise subprocess.TimeoutExpired(cmd, 60)

    runner = FakeRunner(on_call)
    monkeypatch.setattr("shutil.which", lambda _exe: "/usr/bin/codex")
    with pytest.raises(ProviderUnavailable):
        _call(_client(runner))


def test_check_auth_ok_su_login_status_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    def on_call(cmd, **_kw):
        return subprocess.CompletedProcess(cmd, 0, "Logged in using ChatGPT", "")

    runner = FakeRunner(on_call)
    monkeypatch.setattr("shutil.which", lambda _exe: "/usr/bin/codex")
    _client(runner).check_auth()  # non deve sollevare


def test_check_auth_fallisce_su_login_status_non_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    def on_call(cmd, **_kw):
        return subprocess.CompletedProcess(cmd, 1, "", "Not logged in")

    runner = FakeRunner(on_call)
    monkeypatch.setattr("shutil.which", lambda _exe: "/usr/bin/codex")
    with pytest.raises(ProviderAuth):
        _client(runner).check_auth()
