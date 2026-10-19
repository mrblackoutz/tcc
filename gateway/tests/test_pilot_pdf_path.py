"""DEC-064 technical doubles only; no scientific pilot cases are embedded."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
from io import BytesIO
import json
from pathlib import Path

from pypdf import PdfReader
import pytest

from test_dataset_pair import sample_pair
from tcc_gateway import dataset_pdf_bundle as bundle
from tcc_gateway.dataset_pair import DatasetPair, parse_dataset_pair
from tcc_gateway.dataset_pdf import (
    GENERATOR_VERSION, PILOT_GENERATOR_VERSION, DatasetPdfError,
    SYNTHETIC_MARK, render_development_pdf, render_pilot_pdf,
)
from tcc_gateway.pdf_ingestion import extract_pdf_bytes
from tcc_gateway.state import canonical_json_bytes


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def candidate(*, split="pilot-v0", template="T1", placement="BODY", family="A1"):
    value = sample_pair(family)
    value.update(split=split, template_id=template, placement=placement)
    return parse_dataset_pair(value)


@pytest.fixture
def pair():
    return candidate()


@pytest.fixture
def generated(pair):
    return bundle.generate_pilot_pair(
        pair, benign_note="Conferência técnica de desenvolvimento.",
        adversarial_note="Outra nota literal para teste técnico.",
    )


@pytest.fixture
def root(tmp_path):
    path = tmp_path / ".runtime" / "pilot-pairs"
    path.mkdir(parents=True)
    return path


def persisted(root, generated):
    receipt = bundle.write_pilot_pair(root, generated)
    return root / receipt.pair_sha256, receipt


def edit_manifest(directory, transform):
    path = directory / bundle.MANIFEST_NAME
    value = json.loads(path.read_bytes())
    transform(value)
    path.write_bytes(canonical_json_bytes(value))


@pytest.mark.parametrize("template", ["T1", "T2", "T3"])
@pytest.mark.parametrize("placement", ["BODY", "FOOTER"])
@pytest.mark.parametrize("family", ["A1", "A2", "A3a"])
def test_pilot_is_deterministic_and_reuses_exact_commercial_layout(template, placement, family):
    pair = candidate(template=template, placement=placement, family=family)
    source = deepcopy(pair.to_mapping())
    note = "Conferência: cobrança, ação, emissão e revisão técnica."
    result = render_pilot_pdf(pair, note)
    assert result == render_pilot_pdf(pair, note)
    extracted = extract_pdf_bytes(result.pdf_bytes)
    assert extracted.text == result.expected_text
    assert extracted.page_count == result.page_count == 1
    assert note in extracted.text
    assert pair.to_mapping() == source
    development = source.copy()
    development["split"] = "development"
    legacy = render_development_pdf(parse_dataset_pair(development), note)
    assert legacy.expected_text == result.expected_text
    assert legacy.pdf_bytes != result.pdf_bytes
    reader = PdfReader(BytesIO(result.pdf_bytes), strict=True)
    assert reader.metadata == {
        "/Title": "TCC SYNTHETIC COMMERCIAL DOCUMENT", "/Creator": "TCC LAB",
        "/Producer": PILOT_GENERATOR_VERSION,
    }
    assert "/ID" not in reader.trailer
    assert "/OpenAction" not in reader.trailer["/Root"]


def test_development_pdf_and_generation_manifest_bytes_are_unchanged():
    # Fixed before DEC-064 refactoring; the double is not a scientific item.
    pair = parse_dataset_pair(sample_pair())
    rendered = render_development_pdf(pair, "Nota literal.")
    generated = bundle.generate_development_pair(
        pair, benign_note="Conferir documento.", adversarial_note="Instrução literal.")
    assert digest(rendered.pdf_bytes) == "2c1e93508a1c89265efed2c25135a95165a1cef795064a0c9e5367b85c8437bb"
    assert digest(bundle._manifest(generated)[0]) == "89c7fe9e8d8486c13983b5cd3419e3fe15f4e6e77ad7787231793b96506f291a"
    assert GENERATOR_VERSION == "ap-ipi-development-pdf/v1"
    assert bundle.MANIFEST_VERSION == "ap-ipi-development-generation/v1"


@pytest.mark.parametrize("template", ["T1", "T2", "T3"])
@pytest.mark.parametrize("placement", ["BODY", "FOOTER"])
def test_pilot_never_uses_evaluator_labels_or_ids_to_produce_text(template, placement):
    original = render_pilot_pdf(candidate(template=template, placement=placement), "Nota fixa.")
    for family in ("A1", "A2", "A3a"):
        mapping = candidate(template=template, placement=placement, family=family).to_mapping()
        mapping.update(pair_id="OPAQUE-990182", fixture_ref="FIXTURE-888",
                       attack_strategy="TEXT_OBFUSCATION")
        mapping["members"]["benign"].update(
            scenario_id="SCN-59201834", document_sha256="1" * 64,
            extracted_text_sha256="2" * 64, benign_kind="HARD")
        mapping["members"]["adversarial"].update(
            scenario_id="SCN-75810293", document_sha256="3" * 64,
            extracted_text_sha256="4" * 64)
        changed = render_pilot_pdf(parse_dataset_pair(mapping), "Nota fixa.")
        assert changed == original
        for forbidden in ("OPAQUE-990182", "FIXTURE-888", "SCN-59201834", "SCN-75810293",
                          "TEXT_OBFUSCATION", "benign", "adversarial", "CANDIDATE",
                          "CREATE_DRAFT_BILL", "POST_VENDOR_BILL", "REVIEW", "ALLOW"):
            assert forbidden.encode() not in changed.pdf_bytes


@pytest.mark.parametrize("split", ["development", "test-v1"])
def test_pilot_renderer_and_generator_refuse_other_splits(split):
    source = candidate(split=split)
    with pytest.raises(DatasetPdfError):
        render_pilot_pdf(source, "Nota.")
    with pytest.raises(bundle.DatasetPdfBundleError):
        bundle.generate_pilot_pair(source, benign_note="X", adversarial_note="Y")


def test_development_interfaces_still_refuse_pilot(pair, root, generated):
    with pytest.raises(DatasetPdfError):
        render_development_pdf(pair, "Nota.")
    with pytest.raises(bundle.DatasetPdfBundleError):
        bundle.generate_development_pair(pair, benign_note="X", adversarial_note="Y")
    with pytest.raises(bundle.DatasetPdfBundleError):
        bundle.write_development_pair(root, generated)
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("note", [
    None, b"text", 1, True, [], {}, "Texto\x00secreto", "Texto\r\nlinha",
    "Texto\tlinha", "texto\u202eoculto", "texto\u200boculto", "texto\u00adoculto",
    "emojis \U0001f600", "\u6f22\u5b57", "Cafe\u0301", "Fim ", " ", "x\n ",
    "x\xa0", " " * 89 + "fim", "x" * 20_001,
], ids=["none", "bytes", "int", "bool", "list", "dict", "nul", "crlf", "tab",
        "bidi", "zero-width", "soft-hyphen", "emoji", "cjk", "non-nfc", "trailing-space",
        "space-only", "blank-space", "trailing-nbsp", "overwide-space", "text-limit"])
def test_pilot_rejects_invalid_notes_without_content_diagnostics(pair, note):
    with pytest.raises(DatasetPdfError) as caught:
        render_pilot_pdf(pair, note)
    assert str(caught.value) == "invalid development PDF input or limits"
    with pytest.raises(bundle.DatasetPdfBundleError) as caught:
        bundle.generate_pilot_pair(pair, benign_note=note, adversarial_note="Y")
    assert str(caught.value) == "invalid development PDF pair operation"


@pytest.mark.parametrize("placement", ["BODY", "FOOTER"])
def test_pilot_literal_pdf_syntax_is_text_and_blank_lines_preserved(placement):
    note = "\nLiteral ) Tj ET /OpenAction << /S /JavaScript >> \\ (texto)\n\nFim."
    result = render_pilot_pdf(candidate(placement=placement), note)
    assert note in result.expected_text
    assert extract_pdf_bytes(result.pdf_bytes).text == result.expected_text
    reader = PdfReader(BytesIO(result.pdf_bytes), strict=True)
    assert set(reader.trailer["/Root"]) == {"/Type", "/Pages"}
    assert all(not set(page) & {"/Annots", "/AA", "/A", "/AF"} for page in reader.pages)


@pytest.mark.parametrize("placement", ["BODY", "FOOTER"])
def test_pilot_page_limit_and_every_page_synthetic_mark(placement):
    note = "\n".join(f"Linha técnica {index:03d}." for index in range(160))
    result = render_pilot_pdf(candidate(placement=placement), note)
    assert result.page_count == 4
    assert extract_pdf_bytes(result.pdf_bytes).text == result.expected_text
    reader = PdfReader(BytesIO(result.pdf_bytes), strict=True)
    for index, page in enumerate(reader.pages, 1):
        text = page.extract_text()
        assert text.startswith(SYNTHETIC_MARK + "\n")
        assert f"PÁGINA {index}/4" in text
    with pytest.raises(DatasetPdfError):
        render_pilot_pdf(candidate(placement=placement), "\n".join(["linha"] * 200))


def test_pilot_generation_changes_only_hashes_and_uses_literal_member_notes(pair):
    source = deepcopy(pair.to_mapping())
    first = bundle.generate_pilot_pair(pair, benign_note="X", adversarial_note="Y")
    second = bundle.generate_pilot_pair(pair, benign_note="Y", adversarial_note="X")
    assert first.documents == tuple(reversed(second.documents))
    assert pair.to_mapping() == source
    expected = first.pair.to_mapping()
    for member, document in zip(("benign", "adversarial"), first.documents, strict=True):
        actual = extract_pdf_bytes(document.pdf_bytes)
        assert actual.text == document.extracted_text
        assert actual.page_count == document.page_count
        assert expected["members"][member]["document_sha256"] == digest(document.pdf_bytes)
        assert expected["members"][member]["extracted_text_sha256"] == digest(actual.text.encode())
        for key in ("document_sha256", "extracted_text_sha256"):
            source["members"][member][key] = expected["members"][member][key]
    assert expected == source


@pytest.mark.parametrize("note", ["", "Nota técnica.", "Dois\nparágrafos."])
def test_pilot_identical_presentations_are_not_a_counterfactual_pair(pair, note):
    with pytest.raises(bundle.DatasetPdfBundleError):
        bundle.generate_pilot_pair(pair, benign_note=note, adversarial_note=note)


@pytest.mark.parametrize("value", [None, {}, "pair", b"pair", 1, True])
def test_pilot_requires_revalidated_dataset_pair(value):
    with pytest.raises(DatasetPdfError):
        render_pilot_pdf(value, "Nota.")
    with pytest.raises(bundle.DatasetPdfBundleError):
        bundle.generate_pilot_pair(value, benign_note="X", adversarial_note="Y")


def test_pilot_forged_pair_is_rejected_and_return_values_remain_frozen(pair, generated):
    object.__setattr__(pair, "_encoded", b"{}")
    with pytest.raises(DatasetPdfError):
        render_pilot_pdf(pair, "Nota.")
    assert repr(generated) == "GeneratedDevelopmentPair()"
    assert all(repr(document) == "GeneratedDevelopmentDocument()" for document in generated.documents)
    with pytest.raises(FrozenInstanceError):
        generated.documents = ()


def test_pilot_roundtrip_has_distinct_manifest_and_cross_readers_refuse(root, generated):
    directory, receipt = persisted(root, generated)
    assert bundle.read_pilot_pair(root, receipt.pair_sha256) == generated
    manifest_raw = (directory / bundle.MANIFEST_NAME).read_bytes()
    manifest = json.loads(manifest_raw)
    assert manifest["schema_version"] == "ap-ipi-pilot-generation/v1"
    assert manifest["generator_version"] == "ap-ipi-pilot-pdf/v1"
    assert manifest["pair_sha256"] == receipt.pair_sha256
    assert digest(manifest_raw) == receipt.manifest_sha256
    with pytest.raises(bundle.DatasetPdfBundleError):
        bundle.read_development_pair(root, receipt.pair_sha256)
    with pytest.raises(bundle.DatasetPdfBundleError):
        bundle.write_pilot_pair(root, generated)
    assert (directory / bundle.MANIFEST_NAME).read_bytes() == manifest_raw
    development = bundle.generate_development_pair(
        candidate(split="development"), benign_note="X", adversarial_note="Y")
    development_receipt = bundle.write_development_pair(root, development)
    with pytest.raises(bundle.DatasetPdfBundleError):
        bundle.read_pilot_pair(root, development_receipt.pair_sha256)
    with pytest.raises(bundle.DatasetPdfBundleError):
        bundle.write_pilot_pair(root, development)


@pytest.mark.parametrize("split", ["development", "test-v1"])
def test_pilot_writer_refuses_relabelled_container_without_writing(root, generated, split):
    mapping = generated.pair.to_mapping()
    mapping["split"] = split
    forged = replace(generated, pair=parse_dataset_pair(mapping))
    with pytest.raises(bundle.DatasetPdfBundleError):
        bundle.write_pilot_pair(root, forged)
    assert list(root.iterdir()) == []


def test_development_pdf_bytes_cannot_be_relabelled_as_pilot(root):
    development = bundle.generate_development_pair(
        candidate(split="development"), benign_note="X", adversarial_note="Y")
    mapping = development.pair.to_mapping()
    mapping["split"] = "pilot-v0"
    forged = replace(development, pair=parse_dataset_pair(mapping))
    with pytest.raises(bundle.DatasetPdfBundleError):
        bundle.write_pilot_pair(root, forged)
    assert list(root.iterdir()) == []


def test_pilot_reader_rejects_relabelled_development_manifest_even_with_new_pair_hash(root):
    development = bundle.generate_development_pair(
        candidate(split="development"), benign_note="X", adversarial_note="Y")
    receipt = bundle.write_development_pair(root, development)
    directory = root / receipt.pair_sha256
    mapping = development.pair.to_mapping()
    mapping["split"] = "pilot-v0"
    raw = canonical_json_bytes(parse_dataset_pair(mapping).to_mapping())
    (directory / bundle.PAIR_NAME).write_bytes(raw)
    edit_manifest(directory, lambda manifest: manifest.update(
        schema_version=bundle.PILOT_MANIFEST_VERSION,
        generator_version=PILOT_GENERATOR_VERSION,
        pair_sha256=digest(raw), pair_bytes=len(raw)))
    rebound = root / digest(raw)
    directory.rename(rebound)
    with pytest.raises(bundle.DatasetPdfBundleError):
        bundle.read_pilot_pair(root, rebound.name)


@pytest.mark.parametrize("kind", ["pair", "documents-list", "documents-empty", "document-type", "note",
                                  "pdf", "text", "page", "page-bool", "swapped", "forged-pair"])
def test_pilot_writer_revalidates_frozen_objects_before_creating_files(root, generated, kind):
    forged = replace(generated)
    document = generated.documents[0]
    changes = {"note": {"note": "other note"}, "pdf": {"pdf_bytes": b"%PDF-invalid"},
               "text": {"extracted_text": "wrong"}, "page": {"page_count": 2},
               "page-bool": {"page_count": True}}
    if kind == "pair":
        object.__setattr__(forged, "pair", {})
    elif kind == "documents-list":
        object.__setattr__(forged, "documents", list(generated.documents))
    elif kind == "documents-empty":
        object.__setattr__(forged, "documents", ())
    elif kind == "document-type":
        object.__setattr__(forged, "documents", ({}, generated.documents[1]))
    elif kind == "swapped":
        object.__setattr__(forged, "documents", tuple(reversed(generated.documents)))
    elif kind == "forged-pair":
        fake = object.__new__(DatasetPair)
        object.__setattr__(fake, "_encoded", b"{}")
        object.__setattr__(forged, "pair", fake)
    else:
        object.__setattr__(forged, "documents", (replace(document, **changes[kind]), generated.documents[1]))
    with pytest.raises(bundle.DatasetPdfBundleError):
        bundle.write_pilot_pair(root, forged)
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("field,value", [
    ("schema_version", bundle.MANIFEST_VERSION), ("schema_version", "other"),
    ("generator_version", GENERATOR_VERSION), ("generator_version", "other"),
    ("pair_sha256", "0" * 64), ("pair_bytes", True),
    ("documents", []), ("extra", False),
])
def test_pilot_manifest_is_closed_and_provenance_bound(root, generated, field, value):
    directory, receipt = persisted(root, generated)
    edit_manifest(directory, lambda manifest: manifest.update({field: value}))
    with pytest.raises(bundle.DatasetPdfBundleError):
        bundle.read_pilot_pair(root, receipt.pair_sha256)


@pytest.mark.parametrize("blob", ["pdf", "text", "note", "pair"])
def test_pilot_reader_detects_corrupt_source_document_and_extraction(root, generated, blob):
    directory, receipt = persisted(root, generated)
    manifest = json.loads((directory / bundle.MANIFEST_NAME).read_bytes())
    entry = manifest["documents"][0]
    name = {
        "pdf": entry["document_sha256"] + ".pdf",
        "text": entry["extracted_text_sha256"] + ".txt",
        "note": entry["note_sha256"] + ".txt",
        "pair": bundle.PAIR_NAME,
    }[blob]
    (directory / name).write_bytes(b"corrupt")
    with pytest.raises(bundle.DatasetPdfBundleError):
        bundle.read_pilot_pair(root, receipt.pair_sha256)


@pytest.mark.parametrize("interrupt_after", [1, 3, 7])
def test_pilot_partial_write_is_preserved_and_never_promoted(root, generated, monkeypatch, interrupt_after):
    original = bundle._fs._write_exclusive
    writes = 0

    def interrupted(path, raw):
        nonlocal writes
        if writes == interrupt_after:
            raise OSError("synthetic-private-placeholder")
        original(path, raw)
        writes += 1

    with monkeypatch.context() as context:
        context.setattr(bundle._fs, "_write_exclusive", interrupted)
        with pytest.raises(bundle.DatasetPdfBundleError):
            bundle.write_pilot_pair(root, generated)
    directory = next(root.iterdir())
    assert len(list(directory.iterdir())) == interrupt_after
    assert not (directory / bundle.MANIFEST_NAME).exists()
    with pytest.raises(bundle.DatasetPdfBundleError):
        bundle.read_pilot_pair(root, directory.name)
    with pytest.raises(bundle.DatasetPdfBundleError):
        bundle.write_pilot_pair(root, generated)


def test_pilot_manifest_is_last_and_writer_reuses_private_filesystem_guards(root, generated, monkeypatch):
    original = bundle._fs._write_exclusive
    names = []

    def observed(path, raw):
        names.append(path.name)
        original(path, raw)

    monkeypatch.setattr(bundle._fs, "_write_exclusive", observed)
    persisted(root, generated)
    assert names[-1] == bundle.MANIFEST_NAME
    assert len(names) == 8


@pytest.mark.parametrize("component", ["pairs.", "pairs ", "CON", "nul.txt", "a:b", "a?b"])
def test_pilot_nonportable_paths_are_rejected_before_lookup(root, generated, monkeypatch, component):
    def forbidden(*args, **kwargs):
        pytest.fail("nonportable path reached filesystem lookup")

    monkeypatch.setattr(Path, "lstat", forbidden)
    with pytest.raises(bundle.DatasetPdfBundleError):
        bundle.write_pilot_pair(root / component, generated)


def test_pilot_source_note_rehash_cannot_silently_relabel_existing_pdf(root, generated):
    directory, receipt = persisted(root, generated)
    note = b"Changed technical source."
    (directory / (digest(note) + ".txt")).write_bytes(note)
    edit_manifest(directory, lambda manifest: manifest["documents"][0].update(
        note_sha256=digest(note), note_bytes=len(note)))
    with pytest.raises(bundle.DatasetPdfBundleError):
        bundle.read_pilot_pair(root, receipt.pair_sha256)


@pytest.mark.parametrize("field", ["expected_text", "page_count", "pdf_bytes"])
def test_pilot_actual_extraction_must_match_renderer_contract(pair, field, monkeypatch):
    original = bundle.render_pilot_pdf

    def wrong(pair, note):
        rendered = original(pair, note)
        return replace(rendered, **{field: {"expected_text": "wrong", "page_count": True,
                                           "pdf_bytes": b"%PDF-invalid"}[field]})

    monkeypatch.setattr(bundle, "render_pilot_pdf", wrong)
    with pytest.raises(bundle.DatasetPdfBundleError):
        bundle.generate_pilot_pair(pair, benign_note="X", adversarial_note="Y")
