"""DEC-064 generated technical doubles; no scientific pilot payloads here."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path

import pytest

from tcc_gateway import pilot_dataset as pilot
from tcc_gateway.dataset_pair import CODEBOOK_VERSION
from tcc_gateway.state import canonical_json_bytes


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def sample_recipes():
    """Twelve structural doubles, not the local twelve authored pilot items."""
    from test_dataset_pair import sample_pair
    result = {
        "schema_version": pilot.RECIPES_VERSION, "dataset_version": "double-v0",
        "codebook_version": CODEBOOK_VERSION,
        "preparation": {"coordinator_ref": "GUSTAVO", "method": "AI_ASSISTED",
                        "independent_reviewer_ref": "FELIPE",
                        "integration_reviewer_ref": "THOMAZ"},
        "pairs": [],
    }
    strategies = sorted(pilot._STRATEGIES)
    for index in range(12):
        pair = sample_pair(("A1", "A2", "A3a")[index % 3])
        pair.update(split="pilot-v0", dataset_version="double-v0",
                    pair_id=f"PAIR-{index + 7319}", fixture_ref=f"FIX-{index + 2971}",
                    template_id=("T1", "T2", "T3")[index % 3],
                    placement=("BODY", "FOOTER")[index % 2],
                    attack_strategy=strategies[index % 5])
        pair["truth"]["document_ref"] = f"DOC-{index + 5683}"
        for offset, member in enumerate(("benign", "adversarial")):
            pair["members"][member]["scenario_id"] = f"SCN-{index * 2 + offset + 674290}"
            for key in ("document_sha256", "extracted_text_sha256"):
                pair["members"][member][key] = digest(f"double {index} {offset} {key}".encode())
        if index % 2:
            pair["members"]["benign"]["benign_kind"] = "HARD"
        result["pairs"].append({"pair": pair, "benign_note": "Nota estrutural de teste.",
                                "adversarial_note": "Nota estrutural de teste.\nTexto adicional de teste."})
    return result


@pytest.fixture
def recipes():
    return sample_recipes()


@pytest.fixture(scope="module")
def generated():
    return pilot.prepare_pilot_cohort(pilot.parse_pilot_recipes(sample_recipes()), "f" * 64)


@pytest.fixture
def root(tmp_path):
    path = tmp_path / ".runtime" / "pilot-candidates"
    path.mkdir(parents=True)
    return path


def test_canonical_detached_recipes_and_safe_repr(recipes):
    checked = pilot.parse_pilot_recipes(recipes)
    assert repr(checked) == "PilotRecipes()"
    before = deepcopy(recipes)
    recipes["pairs"][0]["benign_note"] = "Modified original"
    detached = checked.to_mapping()
    detached["pairs"][0]["adversarial_note"] = "Modified detached"
    assert checked.to_mapping() == before
    with pytest.raises(FrozenInstanceError):
        checked._encoded = b"{}"


def test_generation_satisfies_shape_hashes_notes_and_pending_gates(generated):
    assert repr(generated) == "GeneratedPilotCohort()"
    assert len(generated.pairs) == 12
    manifest = generated.to_manifest()
    assert manifest["counts"]["families"] == {"A1": 4, "A2": 4, "A3a": 4}
    assert manifest["counts"]["pairs"] == 12
    assert manifest["counts"]["documents"] == 24
    assert manifest["counts"]["hard_benign"] == 6
    assert set(manifest["counts"]["templates"]) == {"T1", "T2", "T3"}
    assert set(manifest["counts"]["placements"]) == {"BODY", "FOOTER"}
    assert set(manifest["counts"]["strategies"]) == pilot._STRATEGIES
    assert manifest["codebook_sha256"] == "f" * 64
    assert manifest["recipes_sha256"] == digest(generated.recipes._encoded)
    assert manifest["human_review_complete"] is False
    assert manifest["scientific_execution_allowed"] is False
    for key in ("independent_review_status", "integration_review_status",
                "a3a_workflow_status", "a3a_approval_status", "final_cross_check_status"):
        assert manifest[key] == "PENDING"
    assert manifest["final_exclusion_status"] == "RESERVED_FOR_PILOT"
    assert "token" not in canonical_json_bytes(manifest).decode()
    documents = []
    for recipe, pair in zip(generated.recipes.to_mapping()["pairs"], generated.pairs, strict=True):
        assert pair.documents[0].note == recipe["benign_note"]
        assert pair.documents[1].note == recipe["adversarial_note"]
        assert pair.documents[1].note.startswith(pair.documents[0].note + "\n")
        assert pair.pair.to_mapping()["split"] == "pilot-v0"
        for member, document in zip(("benign", "adversarial"), pair.documents, strict=True):
            assert pair.pair.to_mapping()["members"][member]["document_sha256"] == digest(document.pdf_bytes)
            documents.append(digest(document.pdf_bytes))
    assert len(set(documents)) == 24
    with pytest.raises(FrozenInstanceError):
        generated.pairs = ()


def test_source_seeds_and_generation_are_deterministic_without_mutation(recipes, generated):
    source = deepcopy(recipes)
    assert pilot.prepare_pilot_cohort(pilot.parse_pilot_recipes(recipes), "f" * 64) == generated
    assert recipes == source
    assert generated.pairs[0].pair.to_mapping()["members"] != recipes["pairs"][0]["pair"]["members"]


@pytest.mark.parametrize("field", ["schema_version", "dataset_version", "codebook_version", "preparation", "pairs"])
def test_missing_top_level_fields(recipes, field):
    del recipes[field]
    with pytest.raises(pilot.PilotDatasetError):
        pilot.parse_pilot_recipes(recipes)


@pytest.mark.parametrize("count", [0, 1, 11, 13])
def test_exactly_twelve_pairs(recipes, count):
    recipes["pairs"] = (recipes["pairs"] * 2)[:count]
    with pytest.raises(pilot.PilotDatasetError):
        pilot.parse_pilot_recipes(recipes)


@pytest.mark.parametrize("scope", ["envelope", "recipe", "preparation", "pair", "truth", "member"])
def test_unknown_fields_and_invented_approval_rejected(recipes, scope):
    target = {"envelope": recipes, "recipe": recipes["pairs"][0],
              "preparation": recipes["preparation"], "pair": recipes["pairs"][0]["pair"],
              "truth": recipes["pairs"][0]["pair"]["truth"],
              "member": recipes["pairs"][0]["pair"]["members"]["benign"]}[scope]
    target["approved"] = True
    with pytest.raises(pilot.PilotDatasetError):
        pilot.parse_pilot_recipes(recipes)


@pytest.mark.parametrize("split", ["development", "test-v1"])
def test_other_splits_rejected(recipes, split):
    recipes["pairs"][0]["pair"]["split"] = split
    with pytest.raises(pilot.PilotDatasetError):
        pilot.parse_pilot_recipes(recipes)


@pytest.mark.parametrize("field,value", [
    ("dataset_version", "another-v0"), ("codebook_version", "unknown-version"),
    ("schema_version", "ap-ipi-pilot-recipes/v2"),
])
def test_versions_homogeneous_and_known(recipes, field, value):
    recipes[field] = value
    with pytest.raises(pilot.PilotDatasetError):
        pilot.parse_pilot_recipes(recipes)


@pytest.mark.parametrize("field", ["dataset_version", "codebook_version"])
def test_pair_version_matches_envelope(recipes, field):
    recipes["pairs"][0]["pair"][field] = "mismatch"
    with pytest.raises(pilot.PilotDatasetError):
        pilot.parse_pilot_recipes(recipes)


@pytest.mark.parametrize("field", ["pair_id", "fixture_ref", "document_ref", "scenario_id", "document_sha256", "extracted_text_sha256"])
def test_global_uniqueness(recipes, field):
    first, second = (recipe["pair"] for recipe in recipes["pairs"][:2])
    if field == "document_ref":
        second["truth"][field] = first["truth"][field]
    elif field in {"scenario_id", "document_sha256", "extracted_text_sha256"}:
        second["members"]["adversarial"][field] = first["members"]["benign"][field]
    else:
        second[field] = first[field]
    with pytest.raises(pilot.PilotDatasetError):
        pilot.parse_pilot_recipes(recipes)


def test_cross_kind_digest_collision_rejected(recipes):
    recipes["pairs"][1]["pair"]["members"]["benign"]["extracted_text_sha256"] = recipes["pairs"][0]["pair"]["members"]["adversarial"]["document_sha256"]
    with pytest.raises(pilot.PilotDatasetError):
        pilot.parse_pilot_recipes(recipes)


@pytest.mark.parametrize("field,replacement", [("template_id", "T1"), ("placement", "BODY"),
                                             ("attack_strategy", "EXPLICIT_INSTRUCTION")])
def test_global_candidate_coverage_required(recipes, field, replacement):
    for recipe in recipes["pairs"]:
        recipe["pair"][field] = replacement
    with pytest.raises(pilot.PilotDatasetError):
        pilot.parse_pilot_recipes(recipes)


def test_family_quotas_not_just_twelve_items(recipes):
    pair = recipes["pairs"][0]["pair"]
    pair.update(attack_family="A2", attack_target="bank_ref")
    pair["truth"]["forbidden_delta_codes"] = ["BANK_REF_APPROVED"]
    with pytest.raises(pilot.PilotDatasetError):
        pilot.parse_pilot_recipes(recipes)


def test_actual_generated_cohort_revalidated_not_just_seed(recipes, generated, monkeypatch):
    monkeypatch.setattr(pilot._bundle, "generate_pilot_pair", lambda *args, **kwargs: generated.pairs[0])
    with pytest.raises(pilot.PilotDatasetError):
        pilot.prepare_pilot_cohort(pilot.parse_pilot_recipes(recipes), "f" * 64)


def test_no_new_hard_benign_quota(recipes):
    for recipe in recipes["pairs"]:
        recipe["pair"]["members"]["benign"]["benign_kind"] = "ORDINARY"
    assert pilot.parse_pilot_recipes(recipes).to_mapping() == recipes


@pytest.mark.parametrize("benign,adversarial", [
    ("", "\nPayload"), (" ", " \nPayload"), ("Original", "Changed\nPayload"),
    ("Original", "OriginalPayload"), ("Original", "Original\n"),
    ("Original", "Original\n\n"), (None, "Payload"),
    ("Original", None), ("Control\x00", "Control\x00\nPayload"),
    ("Original", "Original\nEmoji \U0001f600"),
    ("Original", "Original\nFinal "), ("a" * 20001, "a" * 20001 + "\nPayload"),
], ids=[f"note-{index}" for index in range(12)])
def test_notes_preserve_literal_benign_plus_nonempty_payload(recipes, benign, adversarial):
    recipes["pairs"][0].update(benign_note=benign, adversarial_note=adversarial)
    with pytest.raises(pilot.PilotDatasetError) as caught:
        pilot.parse_pilot_recipes(recipes)
    assert str(caught.value) == "invalid candidate pilot cohort operation"


@pytest.mark.parametrize("field", ["coordinator_ref", "method", "independent_reviewer_ref", "integration_reviewer_ref"])
def test_preparation_declaration_not_claimed_as_completed_review(recipes, field):
    recipes["preparation"][field] = "APPROVED"
    with pytest.raises(pilot.PilotDatasetError):
        pilot.parse_pilot_recipes(recipes)


@pytest.mark.parametrize("value", [None, [], (), 1, True, "source", b"source"])
def test_bad_envelopes_finite(value):
    with pytest.raises(pilot.PilotDatasetError) as caught:
        pilot.parse_pilot_recipes(value)
    assert str(caught.value) == "invalid candidate pilot cohort operation"


@pytest.mark.parametrize("value", [None, True, "f" * 63, "F" * 64, "../outside", b"f" * 64])
def test_codebook_digest_strict(recipes, value):
    with pytest.raises(pilot.PilotDatasetError):
        pilot.prepare_pilot_cohort(pilot.parse_pilot_recipes(recipes), value)


@pytest.mark.parametrize("raw", [b"{}", b"[]", b"null", b"NaN", b'{"pairs":[],"pairs":[]}',
                                 b" " * (pilot.MAX_RECIPES_BYTES + 1)],
                         ids=[f"raw-{index}" for index in range(6)])
def test_raw_constructor_canonical_bounded_duplicate_free(raw):
    with pytest.raises(pilot.PilotDatasetError):
        pilot.PilotRecipes(raw)


def test_forged_frozen_recipes_revalidated(generated):
    forged = pilot.PilotRecipes(generated.recipes._encoded)
    object.__setattr__(forged, "_encoded", b"{}")
    with pytest.raises(pilot.PilotDatasetError):
        pilot.prepare_pilot_cohort(forged, "f" * 64)


@pytest.mark.parametrize("field,value", [("pairs", ()), ("pairs", []), ("recipes", {}),
                                       ("codebook_sha256", "wrong")])
def test_forged_cohort_rejected_before_io(root, generated, field, value):
    forged = replace(generated, **{field: value})
    with pytest.raises(pilot.PilotDatasetError):
        pilot.write_pilot_cohort(root, forged)
    assert list(root.iterdir()) == []


def test_notes_or_order_forgery_refused(root, generated):
    forged_pair = replace(generated.pairs[0], documents=tuple(reversed(generated.pairs[0].documents)))
    forged = replace(generated, pairs=(forged_pair, *generated.pairs[1:]))
    with pytest.raises(pilot.PilotDatasetError):
        pilot.write_pilot_cohort(root, forged)
    assert list(root.iterdir()) == []


def test_roundtrip_hash_named_no_overwrite_and_no_raw_notes_in_manifest(root, generated):
    receipt = pilot.write_pilot_cohort(root, generated)
    directory = root / receipt.cohort_sha256
    assert receipt.cohort_sha256 == receipt.manifest_sha256 == digest((directory / pilot.MANIFEST_NAME).read_bytes())
    assert receipt.recipes_sha256 == digest((directory / pilot.RECIPES_NAME).read_bytes())
    assert pilot.read_pilot_cohort(root, receipt.cohort_sha256) == generated
    assert len(list(directory.iterdir())) == 14
    manifest = (directory / pilot.MANIFEST_NAME).read_bytes()
    assert "Nota estrutural" not in manifest.decode()
    assert json.loads(manifest) == generated.to_manifest()
    with pytest.raises(pilot.PilotDatasetError):
        pilot.write_pilot_cohort(root, generated)
    assert (directory / pilot.MANIFEST_NAME).read_bytes() == manifest


@pytest.mark.parametrize("mode", ["missing_manifest", "missing_recipes", "changed_recipes", "extra_file", "missing_pair", "pair_blob"])
def test_corruption_or_partial_cohort_rejected(root, generated, mode):
    receipt = pilot.write_pilot_cohort(root, generated)
    directory = root / receipt.cohort_sha256
    manifest = json.loads((directory / pilot.MANIFEST_NAME).read_bytes())
    pairdir = directory / manifest["pairs"][0]["pair_sha256"]
    if mode == "missing_manifest":
        (directory / pilot.MANIFEST_NAME).unlink()
    elif mode == "missing_recipes":
        (directory / pilot.RECIPES_NAME).unlink()
    elif mode == "changed_recipes":
        (directory / pilot.RECIPES_NAME).write_bytes(b"{}")
    elif mode == "extra_file":
        (directory / "unexpected").write_bytes(b"extra")
    elif mode == "missing_pair":
        (pairdir / "pair.json").unlink()
    else:
        next(pairdir.glob("*.pdf")).write_bytes(b"tampered")
    with pytest.raises(pilot.PilotDatasetError):
        pilot.read_pilot_cohort(root, receipt.cohort_sha256)


def test_rehashed_manifest_cannot_claim_review_complete(root, generated):
    receipt = pilot.write_pilot_cohort(root, generated)
    directory = root / receipt.cohort_sha256
    manifest = json.loads((directory / pilot.MANIFEST_NAME).read_bytes())
    manifest["human_review_complete"] = True
    raw = canonical_json_bytes(manifest)
    newdigest = digest(raw)
    (directory / pilot.MANIFEST_NAME).write_bytes(raw)
    directory.rename(root / newdigest)
    with pytest.raises(pilot.PilotDatasetError):
        pilot.read_pilot_cohort(root, newdigest)


def test_interrupted_write_keeps_partial_directory_and_no_final_manifest(root, generated, monkeypatch):
    original = pilot._bundle.write_pilot_pair
    calls = 0

    def interrupted(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("sensitive path omitted")
        return original(*args)

    monkeypatch.setattr(pilot._bundle, "write_pilot_pair", interrupted)
    with pytest.raises(pilot.PilotDatasetError) as caught:
        pilot.write_pilot_cohort(root, generated)
    assert "sensitive" not in str(caught.value)
    directory, = root.iterdir()
    assert (directory / pilot.RECIPES_NAME).exists()
    assert not (directory / pilot.MANIFEST_NAME).exists()
    with pytest.raises(pilot.PilotDatasetError):
        pilot.read_pilot_cohort(root, directory.name)
    with pytest.raises(pilot.PilotDatasetError):
        pilot.write_pilot_cohort(root, generated)


@pytest.mark.parametrize("relative", [True, False])
def test_unapproved_roots_refused(tmp_path, generated, relative):
    path = Path(".runtime") if relative else Path.cwd()
    with pytest.raises(pilot.PilotDatasetError):
        pilot.write_pilot_cohort(path, generated)


@pytest.mark.parametrize("identifier", [None, True, "../outside", "f" * 63, "F" * 64])
def test_bad_read_hash_finite(root, identifier):
    with pytest.raises(pilot.PilotDatasetError) as caught:
        pilot.read_pilot_cohort(root, identifier)
    assert str(caught.value) == "invalid candidate pilot cohort operation"
