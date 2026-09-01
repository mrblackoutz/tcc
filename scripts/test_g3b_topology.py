"""Valida a topologia Compose de G3b sem exibir ambiente ou segredos."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROJECT_NAME = "tcc-g3b-offline"


def _compose_config() -> dict[str, Any]:
    command = [
        "docker",
        "compose",
        "--project-name",
        PROJECT_NAME,
        "--env-file",
        str(ROOT / ".env.example"),
        "--profile",
        "g3b",
        "config",
        "--format",
        "json",
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _network_names(service: dict[str, Any]) -> set[str]:
    networks = service.get("networks", {})
    if isinstance(networks, dict):
        return set(networks)
    return set(networks)


def _environment(service: dict[str, Any]) -> dict[str, str]:
    value = service.get("environment", {})
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    result: dict[str, str] = {}
    for item in value:
        name, _, content = str(item).partition("=")
        result[name] = content
    return result


def main() -> None:
    config = _compose_config()
    services = config["services"]
    networks = config["networks"]

    expected_networks = {
        "db": {"lab"},
        "odoo": {"lab"},
        "gateway": {"lab", "llm_control"},
        "llm-client": {"llm_control", "llm_egress"},
        "egress-proxy": {"llm_egress", "proxy_external"},
    }
    for service_name, expected in expected_networks.items():
        actual = _network_names(services[service_name])
        if actual != expected:
            raise RuntimeError(f"unexpected network set for {service_name}")

    for internal_name in ("lab", "llm_control", "llm_egress"):
        if networks[internal_name].get("internal") is not True:
            raise RuntimeError(f"network must be internal: {internal_name}")
    if networks["proxy_external"].get("internal") is True:
        raise RuntimeError("proxy_external must be the sole external network")

    external_members = [
        name
        for name, service in services.items()
        if "proxy_external" in _network_names(service)
    ]
    if external_members != ["egress-proxy"]:
        raise RuntimeError("only egress-proxy may join proxy_external")

    client_environment = _environment(services["llm-client"])
    forbidden_client_names = [
        name
        for name in client_environment
        if name.startswith(("ODOO_", "POSTGRES_"))
        or name in {"DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY_FILE"}
    ]
    if forbidden_client_names:
        raise RuntimeError("llm-client received a forbidden credential environment")
    if client_environment.get("TCC_LLM_CLIENT_MODE") != "mock":
        raise RuntimeError("G3b compose must keep real transport disabled")
    if client_environment.get("HTTPS_PROXY") != "http://egress-proxy:8888":
        raise RuntimeError("llm-client proxy configuration is missing")

    for service_name in ("llm-client", "egress-proxy"):
        service = services[service_name]
        if service.get("read_only") is not True:
            raise RuntimeError(f"service must be read-only: {service_name}")
        if set(service.get("cap_drop", [])) != {"ALL"}:
            raise RuntimeError(f"service must drop all capabilities: {service_name}")
        if service.get("ports"):
            raise RuntimeError(f"service must not publish host ports: {service_name}")
        if "g3b" not in set(service.get("profiles", [])):
            raise RuntimeError(f"service must remain profile-gated: {service_name}")

    print(
        json.dumps(
            {
                "schema_version": "g3b-topology-check/v1",
                "status": "pass",
                "services_checked": sorted(expected_networks),
                "external_network_members": external_members,
                "real_provider_call": False,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
