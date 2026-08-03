from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

_PROMPT_STAGES = frozenset({"planner", "writer", "verifier", "repair"})
_MODEL_STAGES = frozenset({"planner", "writer", "verifier"})


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ValidationStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    REPAIRABLE = "repairable"
    REJECTED = "rejected"


class JobLease(ContractModel):
    job_id: UUID
    schedule_slot: datetime
    attempt_number: int = Field(gt=0)
    policy_version: str


class PreparedRun(ContractModel):
    phase: str
    validation_status: ValidationStatus
    corpus_release_id: str
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_versions: dict[str, str]
    prompt_hashes: dict[str, str]
    models: dict[str, str]
    token_input: int = Field(ge=0)
    token_output: int = Field(ge=0)
    groq_requests: int = Field(ge=0, le=4)
    rate_limits: dict[str, str | int | float | None] = Field(default_factory=dict)
    validation_report: dict[str, object] = Field(default_factory=dict)
    snapshot: dict[str, object] | None = None
    events: tuple[dict[str, object], ...] = ()
    storyline_updates: tuple[dict[str, object], ...] = ()
    entity_updates: tuple[dict[str, object], ...] = ()
    content_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    duration_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def audit_metadata_complete(self) -> PreparedRun:
        if set(self.prompt_versions) != _PROMPT_STAGES:
            raise ValueError("prompt_versions deve coprire planner, writer, verifier e repair")
        if set(self.prompt_hashes) != _PROMPT_STAGES or any(
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
            for value in self.prompt_hashes.values()
        ):
            raise ValueError("prompt_hashes deve contenere quattro SHA-256 completi")
        if set(self.models) != _MODEL_STAGES or any(
            not value.strip() for value in self.models.values()
        ):
            raise ValueError("models deve coprire planner, writer e verifier")
        if self.validation_status == ValidationStatus.PASSED and (
            self.snapshot is None or self.content_hash is None
        ):
            raise ValueError("un run validato richiede snapshot e content_hash")
        return self


class Pipeline(Protocol):
    def execute(self, lease: JobLease) -> PreparedRun: ...


class ControlPlane(Protocol):
    def heartbeat(
        self,
        *,
        worker_id: str,
        status: str,
        version: str,
        hostname: str,
        models: dict[str, str],
        diagnostics: dict[str, object],
    ) -> None: ...

    def lease_next(self, worker_id: str) -> JobLease | None: ...

    def renew_lease(self, job_id: UUID, worker_id: str) -> None: ...

    def submit_run(self, lease: JobLease, worker_id: str, run: PreparedRun) -> UUID: ...

    def publish(self, job_id: UUID, worker_id: str, run_id: UUID) -> dict[str, object]: ...

    def maintain_retention(
        self,
        detailed_days: int,
        storyline_compaction_days: int,
        recurring_inactive_issues: int,
        nonrecurring_keep_issues: int,
    ) -> int: ...

    def fail_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        error_class: str,
        error_message: str,
        retryable: bool,
        available_at: datetime | None = None,
    ) -> None: ...
