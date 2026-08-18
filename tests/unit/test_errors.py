from neveran_gazzetta.domain.errors import NoEvidence, ProviderAuth, ProviderUnavailable


def test_no_evidence_non_e_un_outage() -> None:
    assert NoEvidence.code == "no_evidence"
    assert not NoEvidence.retriable
    assert ProviderUnavailable.code == "provider_unavailable"
    assert ProviderUnavailable.retriable


def test_provider_auth_e_retriable_con_backoff() -> None:
    assert ProviderAuth.code == "provider_auth"
    assert ProviderAuth.retriable
    exc = ProviderAuth("sessione scaduta", retry_after_seconds=300)
    assert exc.retry_after_seconds == 300
