"""Valida estaticamente o gate G3c sem ler ou exibir a chave."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROJECT_NAME = "tcc-g3c-deepseek"


def _compose_config() -> dict[str, Any]:
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            PROJECT_NAME,
            "--env-file",
            str(ROOT / ".env.example"),
            "--profile",
            "g3c",
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _network_names(service: Mapping[str, Any]) -> set[str]:
    networks = service.get("networks", {})
    if isinstance(networks, Mapping):
        return {str(name) for name in networks}
    return {str(name) for name in networks}


def _environment(service: Mapping[str, Any]) -> dict[str, str]:
    value = service.get("environment", {})
    if isinstance(value, Mapping):
        return {str(key): str(item) for key, item in value.items()}
    result: dict[str, str] = {}
    for item in value:
        name, _, content = str(item).partition("=")
        result[name] = content
    return result


def _volume_for(service: Mapping[str, Any], target: str) -> Mapping[str, Any]:
    for volume in service.get("volumes", []):
        if isinstance(volume, Mapping) and volume.get("target") == target:
            return volume
    raise RuntimeError(f"required mount is missing: {target}")


def _assert_hardened(service_name: str, service: Mapping[str, Any]) -> None:
    if service.get("read_only") is not True:
        raise RuntimeError(f"service must be read-only: {service_name}")
    if set(service.get("cap_drop", [])) != {"ALL"}:
        raise RuntimeError(f"service must drop all capabilities: {service_name}")
    if service.get("ports"):
        raise RuntimeError(f"service must not publish host ports: {service_name}")
    if "g3c" not in set(service.get("profiles", [])):
        raise RuntimeError(f"service must remain G3c profile-gated: {service_name}")


def main() -> None:
    config = _compose_config()
    services = config["services"]
    networks = config["networks"]

    expected_networks = {
        "db": {"lab"},
        "odoo": {"lab"},
        "gateway": {"lab", "llm_control"},
        "llm-client-g3c": {"llm_control", "llm_egress"},
        "g3c-runner": {"llm_control"},
        "egress-proxy": {"llm_egress", "proxy_external"},
    }
    for service_name, expected in expected_networks.items():
        if _network_names(services[service_name]) != expected:
            raise RuntimeError(f"unexpected network set for {service_name}")

    for internal_name in ("lab", "llm_control", "llm_egress"):
        if networks[internal_name].get("internal") is not True:
            raise RuntimeError(f"network must be internal: {internal_name}")
    if networks["proxy_external"].get("internal") is True:
        raise RuntimeError("proxy_external must be the sole external network")

    external_members = sorted(
        name
        for name, service in services.items()
        if "proxy_external" in _network_names(service)
    )
    if external_members != ["egress-proxy"]:
        raise RuntimeError("only egress-proxy may join proxy_external")

    client = services["llm-client-g3c"]
    client_environment = _environment(client)
    if client_environment.get("TCC_LLM_CLIENT_MODE") != "deepseek-smoke":
        raise RuntimeError("G3c client must require explicit deepseek-smoke mode")
    if client_environment.get("DEEPSEEK_API_KEY_FILE") != (
        "/run/tcc-secrets/deepseek_api_key"
    ):
        raise RuntimeError("G3c key file configuration is missing")
    if "DEEPSEEK_API_KEY" in client_environment:
        raise RuntimeError("inline DeepSeek key is forbidden")
    if client_environment.get("HTTPS_PROXY") != "http://egress-proxy:8888":
        raise RuntimeError("G3c HTTPS proxy configuration is missing")
    if client_environment.get("HTTP_PROXY") != "http://egress-proxy:8888":
        raise RuntimeError("G3c HTTP proxy configuration is missing")
    if any(name.startswith(("ODOO_", "POSTGRES_")) for name in client_environment):
        raise RuntimeError("G3c client received an ERP credential")

    key_mount = _volume_for(client, "/run/tcc-secrets/deepseek_api_key")
    if key_mount.get("type") != "bind" or key_mount.get("read_only") is not True:
        raise RuntimeError("DeepSeek key must be an exact read-only bind mount")
    if not str(key_mount.get("source", "")).replace("\\", "/").endswith(
        "/.runtime/secrets/deepseek_api_key"
    ):
        raise RuntimeError("DeepSeek key mount source is outside the local runtime path")

    runner = services["g3c-runner"]
    runner_environment = _environment(runner)
    forbidden_runner_names = [
        name
        for name in runner_environment
        if name.startswith(("ODOO_", "POSTGRES_", "DEEPSEEK_"))
        or name in {"HTTP_PROXY", "HTTPS_PROXY"}
    ]
    if forbidden_runner_names:
        raise RuntimeError("G3c runner received a forbidden credential or proxy")
    evidence_mount = _volume_for(runner, "/run/tcc-evidence")
    if evidence_mount.get("type") != "bind" or evidence_mount.get("read_only") is True:
        raise RuntimeError("G3c runner requires only the writable local evidence mount")

    for service_name in ("llm-client-g3c", "g3c-runner", "egress-proxy"):
        _assert_hardened(service_name, services[service_name])

    print(
        json.dumps(
            {
                "schema_version": "g3c-topology-check/v1",
                "status": "pass",
                "services_checked": sorted(expected_networks),
                "external_network_members": external_members,
                "secret_mount": "exact-read-only-local-file",
                "real_provider_call": False,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
