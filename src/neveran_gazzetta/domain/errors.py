"""Errori applicativi stabili e classificabili."""

from __future__ import annotations


class GazzettaError(Exception):
    """Errore base con codice pubblico sanitizzato."""

    code = "gazzetta_error"
    retriable = False


class ConfigurationError(GazzettaError):
    """Configurazione assente o incoerente."""

    code = "configuration_error"


class NoEvidence(GazzettaError):
    """Il corpus è raggiungibile ma non offre evidenze sufficienti."""

    code = "no_evidence"


class ProviderUnavailable(GazzettaError):
    """Un provider necessario non è raggiungibile."""

    code = "provider_unavailable"
    retriable = True


class ReleaseMismatch(GazzettaError):
    """La release del corpus non coincide con quella del run."""

    code = "release_mismatch"
    retriable = True


class ProviderQuota(GazzettaError):
    """Il provider ha esaurito quota o rate limit disponibile."""

    code = "provider_quota"
    retriable = True

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ProviderAuth(GazzettaError):
    """La sessione di autenticazione del provider di generazione non è valida
    (es. login Codex CLI scaduto). Retriable con backoff come ProviderQuota:
    senza un retry_after esplicito, il worker ritenterebbe alla cadenza
    normale invece di aspettare un nuovo login manuale."""

    code = "provider_auth"
    retriable = True

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class InvalidGeneration(GazzettaError):
    """Un output generato non rispetta il contratto."""

    code = "invalid_generation"
    retriable = True


class ArtworkGenerationFailed(GazzettaError):
    """Il servizio immagini non ha prodotto un asset pubblicabile."""

    code = "artwork_generation_failed"

    def __init__(self, message: str, *, reason_code: str, retriable: bool = False) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.retriable = retriable


class PublicationConflict(GazzettaError):
    """Lease o stato non consentono la pubblicazione richiesta."""

    code = "publication_conflict"
    retriable = True


class GenerationQueueEmpty(GazzettaError):
    """Lo slot di pubblicazione è dovuto ma non c'è un'edizione pronta in coda."""

    code = "queue_empty"
    retriable = True
