from __future__ import annotations

import pytest

from tcc_gateway.llm_config import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    OLLAMA_MODEL,
    DeepSeekConfig,
    GenerationSettings,
    LLMConfigError,
    OllamaConfig,
)


SYNTHETIC_KEY = "synthetic-deepseek-key-not-a-credential"


def test_deepseek_loads_key_file_and_hides_secret(tmp_path) -> None:
    key_file = tmp_path / "deepseek-key"
    key_file.write_text(f"{SYNTHETIC_KEY}\n", encoding="utf-8")

    config = DeepSeekConfig.from_env(
        {
            "DEEPSEEK_API_KEY_FILE": str(key_file),
            "DEEPSEEK_BASE_URL": f"{DEEPSEEK_BASE_URL}/",
            "DEEPSEEK_MODEL": DEEPSEEK_MODEL,
            "DEEPSEEK_MAX_OUTPUT_TOKENS": "1024",
        }
    )

    assert config.api_key == SYNTHETIC_KEY
    assert config.base_url == DEEPSEEK_BASE_URL
    assert config.generation.max_output_tokens == 1024
    assert SYNTHETIC_KEY not in repr(config)


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {
            "DEEPSEEK_API_KEY": SYNTHETIC_KEY,
            "DEEPSEEK_API_KEY_FILE": "ignored-synthetic-path",
        },
    ],
)
def test_deepseek_rejects_missing_or_ambiguous_key_without_echo(
    environment: dict[str, str],
) -> None:
    with pytest.raises(LLMConfigError) as captured:
        DeepSeekConfig.from_env(environment)

    assert SYNTHETIC_KEY not in str(captured.value)


def test_deepseek_file_error_hides_path(tmp_path) -> None:
    marker = "SENSITIVE-KEY-PATH-MARKER"
    missing = tmp_path / marker

    with pytest.raises(LLMConfigError) as captured:
        DeepSeekConfig.from_env({"DEEPSEEK_API_KEY_FILE": str(missing)})

    assert marker not in str(captured.value)
    assert str(missing) not in str(captured.value)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://api.deepseek.com",
        "https://example.invalid",
        "https://api.deepseek.com/v1",
        "https://user:synthetic@example.invalid",
        "https://api.deepseek.com?redirect=example.invalid",
        "https://127.0.0.1",
    ],
)
def test_deepseek_rejects_endpoint_outside_allowlist(base_url: str) -> None:
    with pytest.raises(LLMConfigError, match="URL|allowlist|credentials|path"):
        DeepSeekConfig(api_key=SYNTHETIC_KEY, base_url=base_url)


def test_configs_reject_model_drift() -> None:
    with pytest.raises(LLMConfigError, match="DEC-018"):
        DeepSeekConfig(api_key=SYNTHETIC_KEY, model="unselected-model")
    with pytest.raises(LLMConfigError, match="DEC-018"):
        OllamaConfig(model="unselected-model")


@pytest.mark.parametrize(
    "base_url",
    [
        "http://127.0.0.1:11434",
        "http://localhost:11434/",
        "http://ollama:11434",
    ],
)
def test_ollama_accepts_only_declared_local_endpoints(base_url: str) -> None:
    config = OllamaConfig(base_url=base_url)

    assert config.model == OLLAMA_MODEL
    assert config.base_url in {
        "http://127.0.0.1:11434",
        "http://localhost:11434",
        "http://ollama:11434",
    }


@pytest.mark.parametrize(
    "base_url",
    [
        "https://ollama.com",
        "http://127.0.0.1:11435",
        "http://host.docker.internal:11434",
        "http://ollama:11434/api",
    ],
)
def test_ollama_rejects_undeclared_or_cloud_endpoint(base_url: str) -> None:
    with pytest.raises(LLMConfigError, match="allowlist|path"):
        OllamaConfig(base_url=base_url)


def test_g3a_rejects_unrecorded_temperature_change() -> None:
    with pytest.raises(LLMConfigError, match="temperature=0"):
        GenerationSettings(temperature=0.1)
