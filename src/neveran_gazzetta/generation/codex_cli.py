"""Provider di generazione via Codex CLI (GPT online, autenticazione ChatGPT
Pro dell'autore) — implementa lo stesso Protocol GroqPort di CloudflareJsonClient
(generation/pipeline.py), adattato dal provider già in produzione in
neveran-npc-dialogue-forge/worker/providers/codex_cli.py sullo stesso mini PC.

Differenze principali rispetto a quel riferimento:
- ritorna GroqJsonResult (usage tipizzato e obbligatorio), non un GenerationResult
  libero — un'estrazione di usage fallita è un errore (InvalidGeneration), mai un
  0/0 silenzioso che corromperebbe budget e telemetria senza che nessuno se ne
  accorga
- riceve uno schema JSON già pronto (da response_model.model_json_schema in
  pipeline.py), non un path a un file: lo scrive su un file temporaneo
- nessun preflight() come metodo di lifecycle separato (questo worker gira come
  processo oneshot per tick, non un loop persistente da cui chiamarlo una volta
  sola): il controllo di login è in testa a ogni complete_json()
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from neveran_gazzetta.domain.errors import (
    ConfigurationError,
    InvalidGeneration,
    ProviderAuth,
    ProviderQuota,
    ProviderUnavailable,
)
from neveran_gazzetta.generation.models import GroqJsonResult, TokenUsage
from neveran_gazzetta.generation.schema_utils import strict_json_schema

log = logging.getLogger("neveran_gazzetta.codex_cli")

RunnerFn = Callable[..., "subprocess.CompletedProcess[str]"]

# Mai lasciare che una configurazione dimenticata trasformi il flusso Pro
# (incluso nel piano) in consumo API fatturato a parte.
_FORBIDDEN_ENV_KEYS = ("OPENAI_API_KEY", "CODEX_API_KEY")

_AUTH_MARKERS = (
    "not logged in", "not authenticated", "unauthorized", "401", "login required", "auth",
)
_QUOTA_MARKERS = ("rate limit", "rate-limit", "quota", "usage limit", "429", "too many requests")

# Nomi candidati per i campi di usage nell'evento turn.completed: non ancora
# confermati contro un run reale per questo repo (solo per analogia con
# dialogue-forge) — verificato dallo smoke test dal vivo prima della messa in
# produzione, vedi il piano.
_INPUT_TOKEN_KEYS = ("input_tokens", "prompt_tokens")
_OUTPUT_TOKEN_KEYS = ("output_tokens", "completion_tokens")


def _default_runner(cmd: list[str], *, input: str = "", timeout: float | None = None,
                    env: dict[str, str] | None = None, cwd: str | None = None,
                    ) -> subprocess.CompletedProcess[str]:
    """subprocess.run non uccide l'intero process group su timeout, solo il
    processo diretto: se `codex` genera figli resterebbero orfani. Su POSIX
    usiamo una sessione dedicata + SIGKILL al gruppo intero. Il target di
    deploy è sempre Linux (mini PC): i simboli POSIX-only sotto non esistono
    negli stub typeshed per Windows, da qui i type: ignore mirati."""
    popen_kwargs: dict[str, Any] = {}
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env, cwd=cwd, **popen_kwargs,
    )
    try:
        stdout, stderr = proc.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)  # type: ignore[attr-defined]
        else:
            proc.kill()
        proc.communicate()
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def _parse_jsonl_events(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # riga di log non-JSON (non tutte le righe di --json lo sono)
    return events


def _extract_usage(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for ev in events:
        if ev.get("type") == "turn.completed" and isinstance(ev.get("usage"), dict):
            usage: dict[str, Any] = ev["usage"]
            return usage
    return None


def _token_usage_from_raw(usage: dict[str, Any]) -> TokenUsage:
    input_tokens = next((usage[k] for k in _INPUT_TOKEN_KEYS if k in usage), None)
    output_tokens = next((usage[k] for k in _OUTPUT_TOKEN_KEYS if k in usage), None)
    if input_tokens is None or output_tokens is None:
        raise InvalidGeneration(
            f"Campi di usage attesi assenti nell'evento turn.completed: {sorted(usage)}"
        )
    return TokenUsage(input_tokens=int(input_tokens), output_tokens=int(output_tokens))


def _classify_failure(returncode: int, stdout: str, stderr: str) -> tuple[str, str]:
    text = f"{stdout}\n{stderr}".lower()
    if any(m in text for m in _AUTH_MARKERS):
        return "provider_auth", "autenticazione Codex non valida o scaduta (esegui 'codex login')"
    if any(m in text for m in _QUOTA_MARKERS):
        return "provider_quota", "limite/quota Codex raggiunto"
    return "provider_output", f"codex exec terminato con codice {returncode}"


class CodexCliJsonClient:
    def __init__(
        self,
        *,
        executable: str = "codex",
        sandbox: str = "read-only",
        timeout_seconds: float = 600,
        auth_recheck_seconds: float = 300,
        quota_cooldown_seconds: float = 1800,
        reasoning_effort: str = "medium",
        runner: RunnerFn = _default_runner,
    ) -> None:
        self._executable = executable
        self._sandbox = sandbox
        self._timeout_seconds = timeout_seconds
        self._auth_recheck_seconds = auth_recheck_seconds
        self._quota_cooldown_seconds = quota_cooldown_seconds
        self._reasoning_effort = reasoning_effort
        self._runner = runner

    def _sanitized_env(self) -> dict[str, str]:
        env = os.environ.copy()
        for key in _FORBIDDEN_ENV_KEYS:
            env.pop(key, None)
        return env

    def check_auth(self) -> None:
        """Controllo di login esplicito, usato dal preflight CLI prima di un
        deploy live (cli.py) — separato da complete_json() perché lì serve
        comunque rifare il controllo a ogni chiamata."""
        if shutil.which(self._executable) is None:
            raise ConfigurationError(f"eseguibile '{self._executable}' non trovato nel PATH")
        result = self._runner(
            [self._executable, "login", "status"], input="", timeout=30,
            env=self._sanitized_env(), cwd=None,
        )
        if result.returncode != 0:
            raise ProviderAuth(
                "'codex login status' non conferma un login ChatGPT valido — "
                "esegui 'codex login' sul mini PC",
                retry_after_seconds=self._auth_recheck_seconds,
            )

    def complete_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_payload: dict[str, object],
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int,
        strict: bool,
    ) -> GroqJsonResult:
        if shutil.which(self._executable) is None:
            raise ConfigurationError(f"eseguibile '{self._executable}' non trovato nel PATH")

        start = time.time()
        tmpdir = tempfile.mkdtemp(prefix="gazzetta-codex-")
        with contextlib.suppress(OSError):  # no-op su piattaforme senza permessi POSIX
            os.chmod(tmpdir, 0o700)

        try:
            schema_path = Path(tmpdir) / "schema.json"
            schema_path.write_text(
                json.dumps(strict_json_schema(schema) if strict else schema, ensure_ascii=False),
                encoding="utf-8",
            )
            output_path = Path(tmpdir) / "result.json"
            stdin_text = (
                f"{system_prompt}\n\n---\n\n"
                f"{json.dumps(user_payload, ensure_ascii=False, separators=(',', ':'))}"
            )
            instruction_summary = (
                "Genera esclusivamente il frammento JSON richiesto, conforme allo "
                "schema. Il contesto completo è fornito su stdin. Non usare strumenti "
                "e non leggere altri file."
            )
            cmd = [
                self._executable, "exec", "--ephemeral", "--skip-git-repo-check", "--json",
                "--sandbox", self._sandbox,
                "-m", model,
                "-c", f"model_reasoning_effort={self._reasoning_effort}",
                "--output-schema", str(schema_path),
                "-o", str(output_path),
                instruction_summary,
            ]

            log.info("[%s] avviata (codex_cli, modello %s)", schema_name, model)
            try:
                result = self._runner(
                    cmd, input=stdin_text, timeout=self._timeout_seconds,
                    env=self._sanitized_env(), cwd=tmpdir,
                )
            except subprocess.TimeoutExpired as exc:
                raise ProviderUnavailable(
                    f"schema={schema_name}: codex exec oltre il timeout configurato"
                ) from exc
            except FileNotFoundError as exc:
                raise ConfigurationError(f"eseguibile codex non trovato: {exc}") from exc

            duration = time.time() - start

            if result.returncode != 0:
                error_class, message = _classify_failure(
                    result.returncode, result.stdout or "", result.stderr or ""
                )
                log.warning(
                    "[%s] codex exec returncode=%s\n--- stdout ---\n%s\n--- stderr ---\n%s",
                    schema_name, result.returncode,
                    (result.stdout or "")[-2000:], (result.stderr or "")[-2000:],
                )
                if error_class == "provider_auth":
                    raise ProviderAuth(f"schema={schema_name}: {message}",
                                       retry_after_seconds=self._auth_recheck_seconds)
                if error_class == "provider_quota":
                    raise ProviderQuota(f"schema={schema_name}: {message}",
                                        retry_after_seconds=self._quota_cooldown_seconds)
                raise InvalidGeneration(f"schema={schema_name}: {message}")

            if not output_path.exists():
                raise InvalidGeneration(f"schema={schema_name}: file di output -o assente")

            raw_text = output_path.read_text(encoding="utf-8")
            try:
                payload = json.loads(raw_text)
            except JSONDecodeError as exc:
                raise InvalidGeneration(
                    f"schema={schema_name}: output non interpretabile come JSON"
                ) from exc
            if not isinstance(payload, dict):
                raise InvalidGeneration(f"schema={schema_name}: payload JSON non oggetto")

            usage_raw = _extract_usage(_parse_jsonl_events(result.stdout or ""))
            if usage_raw is None:
                raise InvalidGeneration(
                    f"schema={schema_name}: nessun evento turn.completed "
                    "con usage nell'output codex exec"
                )
            usage = _token_usage_from_raw(usage_raw)

            log.info(
                "[%s] completata in %.0fs (modello %s) — usage: %s",
                schema_name, duration, model, usage,
            )
            return GroqJsonResult(payload=payload, usage=usage, rate_limits={})
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
