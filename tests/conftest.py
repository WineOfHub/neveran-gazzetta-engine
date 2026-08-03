from __future__ import annotations

import socket

import pytest


@pytest.fixture(autouse=True)
def block_network_in_offline_suite(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    """La suite standard fallisce se prova ad aprire una connessione reale."""

    if request.node.get_closest_marker("live") is not None:
        return

    original_create_connection = socket.create_connection

    def denied(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Accesso rete vietato nella suite offline")

    def is_loopback(address: object) -> bool:
        if not isinstance(address, tuple) or not address:
            return True
        return str(address[0]).casefold() in {"127.0.0.1", "::1", "localhost"}

    def guarded_create_connection(address: object, *args: object, **kwargs: object):
        if not is_loopback(address):
            denied()
        return original_create_connection(address, *args, **kwargs)

    class OfflineSocket(socket.socket):
        def connect(self, address: object) -> None:
            if not is_loopback(address):
                denied()
            super().connect(address)

        def connect_ex(self, address: object) -> int:
            if not is_loopback(address):
                denied()
            return super().connect_ex(address)

    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    monkeypatch.setattr(socket, "socket", OfflineSocket)
