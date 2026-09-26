from __future__ import annotations

import pytest

from tcc_gateway.config import OdooConfig, OdooConfigError


TOKEN = "synthetic-test-token-do-not-use"


def _base_environment() -> dict[str, str]:
    return {
        "ODOO_BASE_URL": "http://127.0.0.1:8069/",
        "ODOO_DATABASE": "tcc_synthetic",
    }


def test_loads_inline_token_without_exposing_it_in_repr() -> None:
    environment = _base_environment() | {
        "ODOO_API_TOKEN": TOKEN,
        "ODOO_CONNECT_TIMEOUT_SECONDS": "2.5",
        "ODOO_REQUEST_TIMEOUT_SECONDS": "11",
    }

    config = OdooConfig.from_env(environment)

    assert config.base_url == "http://127.0.0.1:8069"
    assert config.database == "tcc_synthetic"
    assert config.api_token == TOKEN
    assert config.connect_timeout_seconds == 2.5
    assert config.request_timeout_seconds == 11.0
    assert TOKEN not in repr(config)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_rejects_nonfinite_odoo_timeout(value: str) -> None:
    environment = _base_environment() | {
        "ODOO_API_TOKEN": TOKEN,
        "ODOO_CONNECT_TIMEOUT_SECONDS": value,
    }
    with pytest.raises(OdooConfigError, match="greater than zero"):
        OdooConfig.from_env(environment)


def test_loads_token_from_secret_file(tmp_path) -> None:
    token_file = tmp_path / "odoo-api-token"
    token_file.write_text(f"{TOKEN}\n", encoding="utf-8")
    environment = _base_environment() | {"ODOO_API_TOKEN_FILE": str(token_file)}

    config = OdooConfig.from_env(environment)

    assert config.api_token == TOKEN
    assert TOKEN not in repr(config)


@pytest.mark.parametrize(
    ("environment", "expected_name"),
    [
        ({"ODOO_DATABASE": "db", "ODOO_API_TOKEN": TOKEN}, "ODOO_BASE_URL"),
        ({"ODOO_BASE_URL": "http://odoo:8069", "ODOO_API_TOKEN": TOKEN}, "ODOO_DATABASE"),
        (
            {"ODOO_BASE_URL": "http://odoo:8069", "ODOO_DATABASE": "db"},
            "ODOO_API_TOKEN",
        ),
    ],
)
def test_rejects_missing_required_configuration(
    environment: dict[str, str], expected_name: str
) -> None:
    with pytest.raises(OdooConfigError) as captured:
        OdooConfig.from_env(environment)

    assert expected_name in str(captured.value)
    assert TOKEN not in str(captured.value)


def test_rejects_ambiguous_token_sources_without_exposing_token(tmp_path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("another-synthetic-token", encoding="utf-8")
    environment = _base_environment() | {
        "ODOO_API_TOKEN": TOKEN,
        "ODOO_API_TOKEN_FILE": str(token_file),
    }

    with pytest.raises(OdooConfigError) as captured:
        OdooConfig.from_env(environment)

    assert TOKEN not in str(captured.value)
    assert "exactly one token source" in str(captured.value)


def test_secret_file_error_does_not_include_path_or_token(tmp_path) -> None:
    missing_file = tmp_path / TOKEN
    environment = _base_environment() | {"ODOO_API_TOKEN_FILE": str(missing_file)}

    with pytest.raises(OdooConfigError) as captured:
        OdooConfig.from_env(environment)

    assert TOKEN not in str(captured.value)
    assert str(missing_file) not in str(captured.value)
