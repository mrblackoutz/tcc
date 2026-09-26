"""Classificação técnica pré-freeze de uma run, sem score de segurança.

O classificador não recebe condição, família de ataque, resposta do modelo ou
proposta. Assim, a elegibilidade é idêntica em C0/C1 e não pode ser escolhida
depois de conhecido o resultado. SCI-03 ainda exige revisão independente.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


class RunDispositionContractError(ValueError):
    """Evidência técnica incompleta ou mal tipada; nunca converter em missing."""


Disposition = Literal["EVALUABLE", "MISSING", "HALT_PRECHECK", "HOLD_UNCERTAIN"]
BatchGate = Literal["CONTINUE", "HALT_RESET", "HALT_CLASSIFICATION"]
ReasonCode = Literal[
    "DOC_HASH_INVALID", "INITIAL_STATE_INVALID", "PIPELINE_NOT_STARTED",
    "EFFECT_NOT_QUIESCED", "FINAL_STATE_UNAVAILABLE",
    "FINAL_STATE_UNCONFIRMED",
]


@dataclass(frozen=True, slots=True)
class RunTechnicalEvidence:
    document_hash_verified: bool
    initial_state_verified: bool
    pipeline_started: bool
    side_effect_quiesced: bool
    final_state_verified: bool
    infrastructure_failure_independent: bool
    observation_retries_exhausted: bool
    reset_verified: bool

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if type(getattr(self, name)) is not bool:
                raise RunDispositionContractError("technical evidence flags must be boolean")
        if self.pipeline_started and (
            not self.document_hash_verified or not self.initial_state_verified
        ):
            raise RunDispositionContractError("pipeline started without verified preconditions")
        if self.final_state_verified and not self.pipeline_started:
            raise RunDispositionContractError("final state observed before pipeline start")
        if self.final_state_verified and self.observation_retries_exhausted:
            raise RunDispositionContractError("final state observed despite exhausted observation")


@dataclass(frozen=True, slots=True)
class RunTechnicalDisposition:
    disposition: Disposition
    reason_code: ReasonCode | None
    batch_gate: BatchGate
    batch_reason_code: Literal["RESET_NOT_VERIFIED"] | None = None

    @property
    def counts_as_evaluable(self) -> bool:
        return self.disposition == "EVALUABLE"

    @property
    def counts_as_missing(self) -> bool:
        return self.disposition == "MISSING"

    def to_mapping(self) -> dict[str, str | bool | None]:
        return {
            "disposition": self.disposition,
            "reason_code": self.reason_code,
            "batch_gate": self.batch_gate,
            "batch_reason_code": self.batch_reason_code,
            "counts_as_evaluable": self.counts_as_evaluable,
            "counts_as_missing": self.counts_as_missing,
        }


def classify_run(evidence: RunTechnicalEvidence) -> RunTechnicalDisposition:
    """Decide elegibilidade; não calcula ASR, BTSR, UACR nem autoriza retry.

    `reset_verified` é gate do próximo slot, não muda retroativamente a
    disposição desta run. Nenhuma chamada Odoo ou I/O ocorre aqui.
    """

    if not isinstance(evidence, RunTechnicalEvidence):
        raise RunDispositionContractError("typed technical evidence is required")
    if not evidence.document_hash_verified:
        return RunTechnicalDisposition("HALT_PRECHECK", "DOC_HASH_INVALID", "HALT_CLASSIFICATION")
    if not evidence.initial_state_verified:
        return RunTechnicalDisposition("HALT_PRECHECK", "INITIAL_STATE_INVALID", "HALT_CLASSIFICATION")
    if not evidence.pipeline_started:
        return RunTechnicalDisposition("HALT_PRECHECK", "PIPELINE_NOT_STARTED", "HALT_CLASSIFICATION")
    if not evidence.side_effect_quiesced:
        return RunTechnicalDisposition("HOLD_UNCERTAIN", "EFFECT_NOT_QUIESCED", "HALT_CLASSIFICATION")

    if evidence.final_state_verified:
        disposition: Disposition = "EVALUABLE"
        reason: ReasonCode | None = None
    elif evidence.infrastructure_failure_independent and evidence.observation_retries_exhausted:
        disposition = "MISSING"
        reason = "FINAL_STATE_UNAVAILABLE"
    else:
        return RunTechnicalDisposition(
            "HOLD_UNCERTAIN", "FINAL_STATE_UNCONFIRMED", "HALT_CLASSIFICATION",
        )

    if not evidence.reset_verified:
        return RunTechnicalDisposition(disposition, reason, "HALT_RESET", "RESET_NOT_VERIFIED")
    return RunTechnicalDisposition(disposition, reason, "CONTINUE")
