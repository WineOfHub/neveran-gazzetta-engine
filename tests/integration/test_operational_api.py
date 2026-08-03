from uuid import uuid4

from fastapi.testclient import TestClient

from neveran_gazzetta.api.app import create_app


def test_health_non_espone_dipendenze() -> None:
    client = TestClient(create_app(service_token="secret-test"))

    response = client.get("/health")

    assert response.status_code == 200
    assert set(response.json()) == {"status", "version"}


def test_endpoint_operativi_sono_fail_closed() -> None:
    client = TestClient(create_app(service_token="secret-test"))

    assert client.get("/v1/status").status_code == 401
    assert client.get(
        "/v1/status", headers={"Authorization": "Bearer wrong"}
    ).status_code == 401
    assert client.get(
        "/v1/status", headers={"Authorization": "Bearer secret-test"}
    ).status_code == 200


def test_non_esistono_endpoint_chat_o_generate_now() -> None:
    client = TestClient(create_app(service_token="secret-test"))

    assert client.post("/ask").status_code == 404
    assert client.post("/generate-now").status_code == 404
    assert client.post(
        "/v1/internal/tick", headers={"Authorization": "Bearer secret-test"}
    ).status_code == 503


def test_run_operativo_richiede_token_e_non_espone_snapshot() -> None:
    run_id = uuid4()
    client = TestClient(
        create_app(
            service_token="secret-test",
            run_provider=lambda value: {"id": str(value), "phase": "completed"},
        )
    )

    assert client.get(f"/v1/runs/{run_id}").status_code == 401
    response = client.get(
        f"/v1/runs/{run_id}",
        headers={"Authorization": "Bearer secret-test"},
    )
    assert response.status_code == 200
    assert response.json() == {"id": str(run_id), "phase": "completed"}
