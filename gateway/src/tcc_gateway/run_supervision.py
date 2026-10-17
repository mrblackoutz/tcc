"""DEC-056: declared timing evidence, not a remote-process supervisor.

This pure contract records one host/clock domain and whether its producer used
mocked or observed facts. It neither authenticates that producer nor establishes
remote termination, health, retries, missingness or permission for an effect.
In particular, cancelling a local wait cannot establish effect quiescence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any, Literal


class RunSupervisionContractError(ValueError):
    """Finite diagnostic; never include received identifiers or payloads."""


StageName = Literal["llm", "observation", "policy", "execution", "capture", "reset"]
SupervisionMode = Literal["MOCKED", "OBSERVED"]
EffectQuiescence = Literal["CONFIRMED", "UNKNOWN"]
_STAGE_NAMES = frozenset({"llm", "observation", "policy", "execution", "capture", "reset"})
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", re.ASCII)
_RUN_ID = re.compile(r"[0-9a-f]{32}", re.ASCII)
_COMMIT = re.compile(r"[0-9a-f]{40}", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}", re.ASCII)


def _matched(value: Any, pattern: re.Pattern[str], message: str) -> None:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise RunSupervisionContractError(message)


def _binding(run_id: Any, condition: Any, code_commit: Any, configuration_sha256: Any) -> None:
    _matched(run_id, _RUN_ID, "invalid supervision run identity")
    if type(condition) is not str or condition not in {"C0", "C1"}:
        raise RunSupervisionContractError("invalid supervision condition")
    _matched(code_commit, _COMMIT, "invalid supervision code commit")
    _matched(configuration_sha256, _SHA256, "invalid supervision configuration digest")


@dataclass(frozen=True, slots=True)
class StageInterval:
    """One elapsed interval in the containing supervision's monotonic domain."""

    name: StageName
    started_ns: int
    ended_ns: int

    def __post_init__(self) -> None:
        if type(self.name) is not str or self.name not in _STAGE_NAMES:
            raise RunSupervisionContractError("invalid supervision stage")
        if any(type(value) is not int or value < 0 for value in (self.started_ns, self.ended_ns)):
            raise RunSupervisionContractError("invalid monotonic interval timestamps")
        if self.ended_ns < self.started_ns:
            raise RunSupervisionContractError("monotonic interval moved backwards")

    def to_mapping(self) -> dict[str, str | int]:
        self.__post_init__()
        return {"name": self.name, "started_ns": self.started_ns, "ended_ns": self.ended_ns}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> StageInterval:
        try:
            if not isinstance(value, Mapping) or set(value) != {"name", "started_ns", "ended_ns"}:
                raise RunSupervisionContractError("closed supervision interval is required")
            return cls(name=value["name"], started_ns=value["started_ns"], ended_ns=value["ended_ns"])
        except (AttributeError, KeyError, TypeError, ValueError):
            raise RunSupervisionContractError("invalid supervision interval mapping") from None


@dataclass(frozen=True, slots=True)
class RunSupervision:
    """Explicit declarations and intervals; no availability or success defaults."""

    run_id: str
    condition: Literal["C0", "C1"]
    code_commit: str
    configuration_sha256: str
    host_id: str
    clock_id: str
    mode: SupervisionMode
    effect_quiescence: EffectQuiescence
    intervals: tuple[StageInterval, ...]

    def __post_init__(self) -> None:
        _binding(self.run_id, self.condition, self.code_commit, self.configuration_sha256)
        _matched(self.host_id, _IDENTIFIER, "invalid supervision host identity")
        _matched(self.clock_id, _IDENTIFIER, "invalid supervision clock identity")
        if type(self.mode) is not str or self.mode not in {"MOCKED", "OBSERVED"}:
            raise RunSupervisionContractError("invalid supervision mode")
        if type(self.effect_quiescence) is not str or self.effect_quiescence not in {"CONFIRMED", "UNKNOWN"}:
            raise RunSupervisionContractError("invalid effect quiescence declaration")
        if type(self.intervals) is not tuple or not 1 <= len(self.intervals) <= len(_STAGE_NAMES):
            raise RunSupervisionContractError("bounded supervision interval tuple is required")
        seen: set[str] = set()
        previous_end: int | None = None
        for interval in self.intervals:
            if type(interval) is not StageInterval:
                raise RunSupervisionContractError("typed supervision intervals are required")
            interval.__post_init__()
            if interval.name in seen:
                raise RunSupervisionContractError("duplicate supervision stage")
            if previous_end is not None and interval.started_ns < previous_end:
                raise RunSupervisionContractError("supervision intervals overlap or are unordered")
            seen.add(interval.name)
            previous_end = interval.ended_ns

    def validate_binding(
        self, *, run_id: str, condition: Literal["C0", "C1"], code_commit: str,
        configuration_sha256: str,
    ) -> None:
        """Compare with independent caller configuration, not a copied envelope."""
        self.__post_init__()
        _binding(run_id, condition, code_commit, configuration_sha256)
        if (self.run_id, self.condition, self.code_commit, self.configuration_sha256) != (
            run_id, condition, code_commit, configuration_sha256,
        ):
            raise RunSupervisionContractError("supervision binding mismatch")

    def to_mapping(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "run_id": self.run_id,
            "condition": self.condition,
            "code_commit": self.code_commit,
            "configuration_sha256": self.configuration_sha256,
            "host_id": self.host_id,
            "clock_id": self.clock_id,
            "mode": self.mode,
            "effect_quiescence": self.effect_quiescence,
            "intervals": [interval.to_mapping() for interval in self.intervals],
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RunSupervision:
        try:
            if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
                raise RunSupervisionContractError("closed supervision mapping is required")
            if type(value["intervals"]) is not list or not 1 <= len(value["intervals"]) <= len(_STAGE_NAMES):
                raise RunSupervisionContractError("bounded supervision interval list is required")
            fields = dict(value)
            fields["intervals"] = tuple(StageInterval.from_mapping(item) for item in value["intervals"])
            return cls(**fields)
        except (AttributeError, KeyError, TypeError, ValueError):
            raise RunSupervisionContractError("invalid supervision mapping") from None
