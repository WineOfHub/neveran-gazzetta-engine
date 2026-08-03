import inspect

from neveran_gazzetta.cli import canary_main, preflight_main


def test_canary_e_preflight_non_contengono_chiamate_di_pubblicazione() -> None:
    source = inspect.getsource(canary_main) + inspect.getsource(preflight_main)

    assert ".lease_next(" not in source
    assert ".submit_run(" not in source
    assert ".materialize(" not in source
    assert ".publish_next(" not in source
    assert "confirm-live-no-publish" in source
    assert "confirm-live-read-only" in source
