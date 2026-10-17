"""The desktop client can log in to an account that uses two-factor login."""

from __future__ import annotations

import pytest

from cloudsync.api import ApiClient, TwoFactorRequired
from cloudsync.config import load_config
from cloudsync.main import EXIT_AUTH, EXIT_OK, main
from tests.conftest import Network


def _turn_on_two_factor(server) -> str:
    from app.core import totp

    api = server.new_api()
    headers = {"Authorization": f"Bearer {api._access}"}
    secret = server.http.post("/api/auth/2fa/setup", headers=headers).json()["secret"]
    code = totp.code_at(secret, totp.current_step())
    server.http.post(
        "/api/auth/2fa/enable", json={"code": code}, headers=headers
    ).raise_for_status()
    return secret


def test_api_login_asks_for_a_code_then_accepts_it(server) -> None:
    from app.core import totp

    secret = _turn_on_two_factor(server)
    api = ApiClient(http=Network(server.http))
    with pytest.raises(TwoFactorRequired):
        api.login(server.email, server.password)
    api.login(server.email, server.password, totp.code_at(secret, totp.current_step() + 1))
    assert api._access


def test_cli_login_takes_an_otp_option(server, tmp_path, monkeypatch, capsys) -> None:
    from app.core import totp

    secret = _turn_on_two_factor(server)
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("CLOUDSYNC_PASSWORD", server.password)
    base = [
        "--config-dir",
        str(cfg),
        "login",
        "--server",
        "http://testserver",
        "--email",
        server.email,
    ]
    base += ["--folder", str(tmp_path / "sync")]
    http = Network(server.http)

    assert main(base, http=http) == EXIT_AUTH  # no code: tells the user what to add
    assert "--otp" in capsys.readouterr().err
    assert not load_config(cfg).is_logged_in

    code = totp.code_at(secret, totp.current_step() + 1)
    assert main([*base, "--otp", code], http=http) == EXIT_OK
    assert load_config(cfg).is_logged_in
