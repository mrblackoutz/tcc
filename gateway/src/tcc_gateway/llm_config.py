"""Configuracao pre-piloto dos provedores LLM sem segredos em diagnosticos."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_DOCUMENTED_BACKEND = "DeepSeek-V4-Flash-0731"
OLLAMA_MODEL = "qwen3:14b-q4_K_M"
OLLAMA_ALLOWED_BASE_URLS = frozenset(
    {
        "http://127.0.0.1:11434",
        "http://localhost:11434",
        "http://ollama:11434",
    }
)


class LLMConfigError(ValueError):
    """Indica configuracao ausente, ambigua ou fora da DEC-018/DEC-020."""


def _normalise_base_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LLMConfigError("LLM base URL must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise LLMConfigError("LLM base URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise LLMConfigError("LLM base URL must not contain a query or fragment")
    if parsed.path not in {"", "/"}:
        raise LLMConfigError("LLM base URL must not contain a path")

    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def _positive_float(environ: Mapping[str, str], name: str, default: float) -> float:
    raw_value = environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        value = float(raw_value)
    except ValueError:
        raise LLMConfigError(f"configuration must be numeric: {name}") from None
    if value <= 0:
        raise LLMConfigError(f"configuration must be greater than zero: {name}")
    return value


def _positive_int(environ: Mapping[str, str], name: str, default: int) -> int:
    raw_value = environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        raise LLMConfigError(f"configuration must be an integer: {name}") from None
    if value <= 0:
        raise LLMConfigError(f"configuration must be greater than zero: {name}")
    return value


def _read_deepseek_key(environ: Mapping[str, str]) -> str:
    inline_key = environ.get("DEEPSEEK_API_KEY", "").strip()
    key_file = environ.get("DEEPSEEK_API_KEY_FILE", "").strip()
    if inline_key and key_file:
        raise LLMConfigError(
            "configure exactly one key source: DEEPSEEK_API_KEY or DEEPSEEK_API_KEY_FILE"
        )
    if inline_key:
        return inline_key
    if not key_file:
        raise LLMConfigError(
            "required configuration is missing: DEEPSEEK_API_KEY or DEEPSEEK_API_KEY_FILE"
        )
    try:
        key = Path(key_file).read_text(encoding="utf-8").strip()
    except OSError:
        raise LLMConfigError("unable to read the configured DeepSeek key file") from None
    if not key:
        raise LLMConfigError("the configured DeepSeek key file is empty")
    return key


@dataclass(frozen=True, slots=True)
class GenerationSettings:
    """Parametros candidatos de G3a; ainda nao constituem freeze experimental."""

    temperature: float = 0.0
    max_output_tokens: int = 2_048
    connect_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.temperature != 0.0:
            raise LLMConfigError("G3a requires temperature=0 until the pilot decides otherwise")
        if self.max_output_tokens <= 0:
            raise LLMConfigError("max output tokens must be greater than zero")
        if self.connect_timeout_seconds <= 0 or self.request_timeout_seconds <= 0:
            raise LLMConfigError("timeouts must be greater than zero")

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str],
        *,
        prefix: str,
    ) -> GenerationSettings:
        raw_temperature = environ.get(f"{prefix}_TEMPERATURE", "0").strip() or "0"
        try:
            temperature = float(raw_temperature)
        except ValueError:
            raise LLMConfigError(
                f"configuration must be numeric: {prefix}_TEMPERATURE"
            ) from None
        return cls(
            temperature=temperature,
            max_output_tokens=_positive_int(
                environ, f"{prefix}_MAX_OUTPUT_TOKENS", 2_048
            ),
            connect_timeout_seconds=_positive_float(
                environ, f"{prefix}_CONNECT_TIMEOUT_SECONDS", 5.0
            ),
            request_timeout_seconds=_positive_float(
                environ, f"{prefix}_REQUEST_TIMEOUT_SECONDS", 60.0
            ),
        )


@dataclass(frozen=True, slots=True)
class DeepSeekConfig:
    api_key: str = field(repr=False)
    base_url: str = DEEPSEEK_BASE_URL
    model: str = DEEPSEEK_MODEL
    generation: GenerationSettings = field(default_factory=GenerationSettings)

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise LLMConfigError("DeepSeek API key must not be empty")
        normalised = _normalise_base_url(self.base_url)
        if normalised != DEEPSEEK_BASE_URL:
            raise LLMConfigError("DeepSeek endpoint is outside the DEC-020 allowlist")
        object.__setattr__(self, "base_url", normalised)
        if self.model != DEEPSEEK_MODEL:
            raise LLMConfigError("DeepSeek model differs from DEC-018")

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None
    ) -> DeepSeekConfig:
        source = os.environ if environ is None else environ
        return cls(
            _read_deepseek_key(source),
            base_url=source.get("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL).strip()
            or DEEPSEEK_BASE_URL,
            model=source.get("DEEPSEEK_MODEL", DEEPSEEK_MODEL).strip()
            or DEEPSEEK_MODEL,
            generation=GenerationSettings.from_env(source, prefix="DEEPSEEK"),
        )


@dataclass(frozen=True, slots=True)
class OllamaConfig:
    base_url: str = "http://127.0.0.1:11434"
    model: str = OLLAMA_MODEL
    generation: GenerationSettings = field(default_factory=GenerationSettings)

    def __post_init__(self) -> None:
        normalised = _normalise_base_url(self.base_url)
        if normalised not in OLLAMA_ALLOWED_BASE_URLS:
            raise LLMConfigError("Ollama endpoint is outside the DEC-020 allowlist")
        object.__setattr__(self, "base_url", normalised)
        if self.model != OLLAMA_MODEL:
            raise LLMConfigError("Ollama model differs from DEC-018")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> OllamaConfig:
        source = os.environ if environ is None else environ
        return cls(
            base_url=source.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip()
            or "http://127.0.0.1:11434",
            model=source.get("OLLAMA_MODEL", OLLAMA_MODEL).strip() or OLLAMA_MODEL,
            generation=GenerationSettings.from_env(source, prefix="OLLAMA"),
        )
