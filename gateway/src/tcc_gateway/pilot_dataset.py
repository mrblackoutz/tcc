"""DEC-064 local candidate cohort, never scientific or financial authority.

Recipes include local source notes and must stay beneath ignored .runtime.
Hashes bind local bytes, not authorship, privacy, independent review or custody.
The 12-item shape is tested with doubles, not a versioned scientific cohort.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
from typing import Any

from . import run_record_store as _fs
from .dataset_pair import CODEBOOK_VERSION, DatasetPair, parse_dataset_pair
from . import dataset_pdf_bundle as _bundle
from .dataset_pdf import _valid_text
from .state import canonical_json_bytes


RECIPES_VERSION = "ap-ipi-pilot-recipes/v1"
COHORT_VERSION = "ap-ipi-pilot-cohort/v1"
MAX_RECIPES_BYTES = 2 * 1024 * 1024
MAX_COHORT_MANIFEST_BYTES = 32 * 1024
RECIPES_NAME = "recipes.json"
MANIFEST_NAME = "cohort.json"
_ERROR = "invalid candidate pilot cohort operation"
_FAILURES = (OSError, ValueError, TypeError, AttributeError, KeyError,
             OverflowError, RecursionError)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PREPARATION = {"coordinator_ref": "GUSTAVO", "method": "AI_ASSISTED",
                "independent_reviewer_ref": "FELIPE",
                "integration_reviewer_ref": "THOMAZ"}
_STRATEGIES = {"EXPLICIT_INSTRUCTION", "FALSE_AUTHORITY", "PROCEDURAL_NOTE",
               "TEXT_OBFUSCATION", "CONTEXTUAL_INSTRUCTION"}
_MEMBERS = ("benign", "adversarial")


class PilotDatasetError(ValueError):
    """Finite failure without notes, documents, paths or source values."""


def _fail() -> None:
    raise PilotDatasetError(_ERROR)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: Any) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail()
    return value


def _cohort_pairs(pairs: tuple[DatasetPair, ...]) -> list[dict]:
    if type(pairs) is not tuple or len(pairs) != 12:
        _fail()
    values = []
    for pair in pairs:
        if type(pair) is not DatasetPair:
            _fail()
        value = parse_dataset_pair(pair.to_mapping()).to_mapping()
        if value["split"] != "pilot-v0":
            _fail()
        values.append(value)
    if (len({value["dataset_version"] for value in values}) != 1
            or {value["codebook_version"] for value in values} != {CODEBOOK_VERSION}
            or Counter(value["attack_family"] for value in values)
            != Counter({"A1": 4, "A2": 4, "A3a": 4})
            or {value["template_id"] for value in values} != {"T1", "T2", "T3"}
            or {value["placement"] for value in values} != {"BODY", "FOOTER"}
            or {value["attack_strategy"] for value in values} != _STRATEGIES):
        _fail()
    for field_name in ("pair_id", "fixture_ref"):
        if len({value[field_name] for value in values}) != 12:
            _fail()
    if len({value["truth"]["document_ref"] for value in values}) != 12:
        _fail()
    members = [value["members"][name] for value in values for name in _MEMBERS]
    if len({member["scenario_id"] for member in members}) != 24:
        _fail()
    digests = [member[key] for member in members
               for key in ("document_sha256", "extracted_text_sha256")]
    if len(set(digests)) != 48:
        _fail()
    return values


def _validate_recipes(value: Any) -> bytes:
    if (type(value) is not dict
            or any(type(key) is not str for key in value)
            or set(value) != {"schema_version", "dataset_version", "codebook_version",
                              "preparation", "pairs"}
            or value["schema_version"] != RECIPES_VERSION
            or any(type(value[key]) is not str for key in (
                "schema_version", "dataset_version", "codebook_version"))
            or type(value["preparation"]) is not dict
            or value["preparation"] != _PREPARATION
            or any(type(key) is not str or type(item) is not str
                   for key, item in value["preparation"].items())
            or type(value["pairs"]) is not list or len(value["pairs"]) != 12):
        _fail()
    parsed = []
    for recipe in value["pairs"]:
        if (type(recipe) is not dict
                or any(type(key) is not str for key in recipe)
                or set(recipe) != {"pair", "benign_note", "adversarial_note"}):
            _fail()
        pair = parse_dataset_pair(recipe["pair"])
        benign, adversarial = recipe["benign_note"], recipe["adversarial_note"]
        _valid_text(benign)
        _valid_text(adversarial)
        if (not benign.strip() or not adversarial.startswith(benign + "\n")
                or not adversarial[len(benign) + 1:].strip()):
            _fail()
        parsed.append(pair)
    mappings = _cohort_pairs(tuple(parsed))
    if any(value[key] != pair[key] for pair in mappings
           for key in ("dataset_version", "codebook_version")):
        _fail()
    raw = canonical_json_bytes(value)
    if not 0 < len(raw) <= MAX_RECIPES_BYTES:
        _fail()
    return raw


def _decode_recipes(raw: bytes) -> dict:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_RECIPES_BYTES:
        _fail()
    value = _fs._json(raw)
    if _validate_recipes(value) != raw:
        _fail()
    return value


@dataclass(frozen=True, slots=True)
class PilotRecipes:
    _encoded: bytes = field(repr=False)

    def __post_init__(self) -> None:
        self.to_mapping()

    def to_mapping(self) -> dict:
        try:
            return _decode_recipes(self._encoded)
        except _FAILURES:
            raise PilotDatasetError(_ERROR) from None


@dataclass(frozen=True, slots=True)
class GeneratedPilotCohort:
    recipes: PilotRecipes = field(repr=False)
    codebook_sha256: str = field(repr=False)
    pairs: tuple[_bundle.GeneratedDevelopmentPair, ...] = field(repr=False)

    def to_manifest(self) -> dict:
        """Detached integrity summary with permanently pending review gates."""
        try:
            return _fs._json(_manifest(_checked(self)))
        except _FAILURES:
            raise PilotDatasetError(_ERROR) from None


@dataclass(frozen=True, slots=True)
class PilotCohortWriteReceipt:
    cohort_sha256: str
    manifest_sha256: str
    recipes_sha256: str


def parse_pilot_recipes(value: dict) -> PilotRecipes:
    try:
        return PilotRecipes(_validate_recipes(value))
    except _FAILURES:
        raise PilotDatasetError(_ERROR) from None


def prepare_pilot_cohort(recipes: PilotRecipes, codebook_sha256: str) -> GeneratedPilotCohort:
    """Generate documents from explicit notes, never from evaluator labels."""
    try:
        if type(recipes) is not PilotRecipes:
            _fail()
        codebook_sha256 = _digest(codebook_sha256)
        checked = parse_pilot_recipes(recipes.to_mapping())
        pairs = tuple(_bundle.generate_pilot_pair(
            parse_dataset_pair(recipe["pair"]), benign_note=recipe["benign_note"],
            adversarial_note=recipe["adversarial_note"],
        ) for recipe in checked.to_mapping()["pairs"])
        _cohort_pairs(tuple(pair.pair for pair in pairs))
        return GeneratedPilotCohort(checked, codebook_sha256, pairs)
    except _FAILURES:
        raise PilotDatasetError(_ERROR) from None


def _checked(value: GeneratedPilotCohort) -> GeneratedPilotCohort:
    if type(value) is not GeneratedPilotCohort:
        _fail()
    if (type(value.recipes) is not PilotRecipes or type(value.pairs) is not tuple
            or len(value.pairs) != 12
            or any(type(pair) is not _bundle.GeneratedDevelopmentPair for pair in value.pairs)):
        _fail()
    rebuilt = prepare_pilot_cohort(value.recipes, value.codebook_sha256)
    if rebuilt != value:
        _fail()
    return rebuilt


def _manifest(value: GeneratedPilotCohort) -> bytes:
    recipes = value.recipes.to_mapping()
    mappings = _cohort_pairs(tuple(pair.pair for pair in value.pairs))
    return canonical_json_bytes({
        "schema_version": COHORT_VERSION, "split": "pilot-v0", "status": "CANDIDATE",
        "dataset_version": recipes["dataset_version"],
        "codebook_version": recipes["codebook_version"],
        "codebook_sha256": value.codebook_sha256,
        "generator_version": _bundle.PILOT_GENERATOR_VERSION,
        "recipes_sha256": _sha256(value.recipes._encoded),
        "preparation": dict(_PREPARATION),
        "independent_review_status": "PENDING", "integration_review_status": "PENDING",
        "human_review_complete": False, "scientific_execution_allowed": False,
        "a3a_workflow_status": "PENDING", "a3a_approval_status": "PENDING",
        "final_exclusion_status": "RESERVED_FOR_PILOT",
        "final_cross_check_status": "PENDING",
        "counts": {"pairs": 12, "documents": 24,
                   "families": dict(Counter(pair["attack_family"] for pair in mappings)),
                   "templates": dict(Counter(pair["template_id"] for pair in mappings)),
                   "placements": dict(Counter(pair["placement"] for pair in mappings)),
                   "strategies": dict(Counter(pair["attack_strategy"] for pair in mappings)),
                   "hard_benign": sum(pair["members"]["benign"]["benign_kind"] == "HARD"
                                      for pair in mappings)},
        "pairs": [{"pair_sha256": _sha256(canonical_json_bytes(pair)),
                   "pair_id": pair["pair_id"], "fixture_ref": pair["fixture_ref"],
                   "document_ref": pair["truth"]["document_ref"],
                   "scenario_ids": [pair["members"][member]["scenario_id"] for member in _MEMBERS]}
                  for pair in mappings],
    })


def _entries(directory: Path, hashes: set[str]) -> None:
    expected = {RECIPES_NAME, MANIFEST_NAME, *hashes}
    names = set()
    for path in directory.iterdir():
        names.add(path.name)
        if len(names) > 14:
            _fail()
    if names != expected:
        _fail()
    for name in (RECIPES_NAME, MANIFEST_NAME):
        _fs._regular_file((directory / name).lstat())
    for digest in hashes:
        _fs._directory_chain(directory / digest)


def write_pilot_cohort(root: Path, cohort: GeneratedPilotCohort) -> PilotCohortWriteReceipt:
    """Exclusive local write; interrupted directories are retained, not repaired."""
    try:
        checked = _checked(cohort)
        manifest = _manifest(checked)
        cohort_sha256 = _sha256(manifest)
        root, root_identity = _fs._root(root)
        directory = root / cohort_sha256
        _fs._verify_directory(root, root_identity)
        directory.mkdir(mode=0o700, exist_ok=False)
        identity = _fs._identity(_fs._directory_chain(directory))
        _fs._verify_directory(root, root_identity)
        _fs._write_exclusive(directory / RECIPES_NAME, checked.recipes._encoded)
        hashes = set()
        for pair in checked.pairs:
            _fs._verify_directory(directory, identity)
            _fs._verify_directory(root, root_identity)
            receipt = _bundle.write_pilot_pair(directory, pair)
            hashes.add(receipt.pair_sha256)
        _fs._verify_directory(directory, identity)
        _fs._verify_directory(root, root_identity)
        _fs._write_exclusive(directory / MANIFEST_NAME, manifest)
        _fs._verify_directory(directory, identity)
        _fs._verify_directory(root, root_identity)
        _entries(directory, hashes)
        if read_pilot_cohort(root, cohort_sha256) != checked:
            _fail()
        return PilotCohortWriteReceipt(cohort_sha256, cohort_sha256,
                                       _sha256(checked.recipes._encoded))
    except _FAILURES:
        raise PilotDatasetError(_ERROR) from None


def read_pilot_cohort(root: Path, cohort_sha256: str) -> GeneratedPilotCohort:
    """Recheck every source recipe and pair; refuse partial or relabelled sets."""
    try:
        cohort_sha256 = _digest(cohort_sha256)
        root, root_identity = _fs._root(root)
        directory = root / cohort_sha256
        identity = _fs._identity(_fs._directory_chain(directory))
        raw = _fs._read_bounded(directory / MANIFEST_NAME, MAX_COHORT_MANIFEST_BYTES)
        if _sha256(raw) != cohort_sha256:
            _fail()
        manifest = _fs._json(raw)
        recipes_raw = _fs._read_bounded(directory / RECIPES_NAME, MAX_RECIPES_BYTES)
        recipes = PilotRecipes(recipes_raw)
        expected = prepare_pilot_cohort(recipes, manifest["codebook_sha256"])
        if raw != _manifest(expected):
            _fail()
        hashes = set()
        for pair in expected.pairs:
            pair_sha256 = _sha256(canonical_json_bytes(pair.pair.to_mapping()))
            if _bundle.read_pilot_pair(directory, pair_sha256) != pair:
                _fail()
            hashes.add(pair_sha256)
        _entries(directory, hashes)
        _fs._verify_directory(directory, identity)
        _fs._verify_directory(root, root_identity)
        return expected
    except _FAILURES:
        raise PilotDatasetError(_ERROR) from None
