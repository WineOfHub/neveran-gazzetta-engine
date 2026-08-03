from neveran_gazzetta.domain.errors import NoEvidence, ProviderUnavailable


def test_no_evidence_non_e_un_outage() -> None:
    assert NoEvidence.code == "no_evidence"
    assert not NoEvidence.retriable
    assert ProviderUnavailable.code == "provider_unavailable"
    assert ProviderUnavailable.retriable
