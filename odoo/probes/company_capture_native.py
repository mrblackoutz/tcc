# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-055 administrative, read-only company capture for disposable fixtures.

No RPC endpoint, mutation, approval, commit, retry or restore is exposed here.
The caller owns a *new* ordinary registry cursor and marks its transaction
READ ONLY before constructing the environment. Complete output is local raw
evidence; it is not publishable project documentation.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path, PurePosixPath
import re
import stat

from tcc_gateway.company_capture import (
    BOOLEAN_FIELDS, CAPTURE_VERSION, CaptureBinding, CompanyCaptureError,
    DECIMAL_FIELDS, INTEGER_FIELDS, JSON_FIELDS, JSON_ID_NAMES,
    JSON_RELATION_PATHS, MANY_RELATIONS, RELATIONS, ROW_FIELDS, capture_sha256,
)
from tcc_gateway.state import canonical_json_sha256


MAX_ROWS = 25_000
MAX_FILES = 10_000
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_FILESTORE_BYTES = 512 * 1024 * 1024
PSEUDO_MODELS = frozenset({"postgres.sequence", "outbox"})
SPECIAL_FIELDS = {
    "ir.attachment": {"content_sha256", "res_ordinal"},
    "mail.message": {"res_ordinal", "subtype_ref"},
}


def _require(value):
    if not value:
        raise CompanyCaptureError("native company capture rejected")


def decimal_text(value, *, money=False):
    """Preserve native finite decimal values; do not round quantities away."""
    _require(type(value) in {int, float, Decimal, str})
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise CompanyCaptureError("native company capture rejected") from None
    _require(number.is_finite())
    if money:
        # The endpoint contract is two-decimal, independently of reset fields.
        _require(number == number.quantize(Decimal("0.01")))
        return format(number, ".2f")
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if number == 0 else text


def _regular_file(path, root):
    """Reject symlinks and parent traversal, including symlink ancestors."""
    _require(isinstance(path, Path) and isinstance(root, Path))
    _require(root.is_absolute() and root.is_dir() and not root.is_symlink())
    _require(path.is_relative_to(root))
    current = root
    for piece in path.relative_to(root).parts:
        _require(piece not in {"", ".", ".."})
        current = current / piece
        _require(not current.is_symlink())
    info = path.stat()
    _require(stat.S_ISREG(info.st_mode) and 0 <= info.st_size <= MAX_FILE_BYTES)
    return info


def _file_digest(path, root, *, expected_sha1=None):
    before = _regular_file(path, root)
    digest = hashlib.sha256()
    sha1 = hashlib.sha1(usedforsecurity=False)
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            _require(size <= MAX_FILE_BYTES)
            digest.update(chunk)
            sha1.update(chunk)
    after = _regular_file(path, root)
    _require(size == before.st_size == after.st_size and
             (before.st_mtime_ns, before.st_ino) == (after.st_mtime_ns, after.st_ino))
    if expected_sha1 is not None:
        _require(type(expected_sha1) is str and expected_sha1 == sha1.hexdigest())
    return {"path": path.relative_to(root).as_posix(), "size": size,
            "sha256": digest.hexdigest()}


def filestore_projection(root):
    """Hash every regular file, including orphan and Odoo checklist files."""
    root = Path(root)
    _require(root.is_absolute() and root.is_dir() and not root.is_symlink())
    result = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        _require(not path.is_symlink())
        info = path.stat()
        if stat.S_ISDIR(info.st_mode):
            continue
        _require(stat.S_ISREG(info.st_mode))
        result.append(_file_digest(path, root))
        _require(len(result) <= MAX_FILES and
                 sum(item["size"] for item in result) <= MAX_FILESTORE_BYTES)
    return result


def _json_relations(value, visit, *, contract, path=(), depth=0):
    """Normalize only allowlisted *paths* of one known persisted contract."""
    _require(depth <= 20)
    _require(contract in JSON_RELATION_PATHS)
    paths = JSON_RELATION_PATHS[contract]
    if type(value) is dict:
        result = {}
        for key, item in value.items():
            _require(type(key) is str)
            item_path = (*path, key)
            if item_path in paths:
                model = paths[item_path]
                if item is None:
                    result[key] = None
                elif key.endswith("_ids"):
                    _require(type(item) is list and all(type(x) is int and x > 0 for x in item))
                    result[key] = sorted(visit(model, x) for x in item)
                else:
                    _require(type(item) is int and item > 0)
                    result[key] = visit(model, item)
            else:
                _require(key not in JSON_ID_NAMES)
                result[key] = _json_relations(item, visit, contract=contract,
                                               path=item_path, depth=depth + 1)
        return result
    if type(value) is list:
        return [_json_relations(item, visit, contract=contract, path=(*path, "[]"),
                                depth=depth + 1) for item in value]
    _require(value is None or type(value) in {str, int, bool})
    return value


def _linked_domain(model_field, resource_ids):
    parts = []
    for model, ids in sorted(resource_ids.items()):
        if ids and model not in PSEUDO_MODELS:
            parts.append(["&", (model_field, "=", model), ("res_id", "in", sorted(ids))])
    if not parts:
        return [("id", "=", 0)]
    return ["|"] * (len(parts) - 1) + [item for part in parts for item in part]


def _source_fields(model):
    result = [name for name in ROW_FIELDS[model]
              if name not in SPECIAL_FIELDS.get(model, set())]
    if model in {"ir.attachment", "mail.message"}:
        result.append("res_id")
    if model == "mail.message":
        result.append("subtype_id")
    return result


def _native_rows(env, model, ids):
    _require(len(ids) <= MAX_ROWS)
    if not ids:
        return []
    records = env[model].browse(sorted(ids)).exists()
    _require(records.ids == sorted(ids))
    fields = _source_fields(model)
    _require(all(name in env[model]._fields for name in fields))
    rows = records.read(fields, load=False)
    _require([row["id"] for row in rows] == sorted(ids))
    return rows


def _roots(env, company_id):
    ids = {model: set() for model in ROW_FIELDS if model not in PSEUDO_MODELS}
    ids["res.company"].add(company_id)
    # These actors pre-exist effects. Discovering their partner only through a
    # later message would change ordinal membership, not actual master data.
    ids["res.users"].update(env["res.users"].search([
        ("company_ids", "in", [company_id])], order="id").ids)
    for model in ("account.move", "purchase.order", "purchase.order.line", "account.journal",
                  "account.payment", "ap.security.draft.receipt", "ap.security.po.guard",
                  "ap.security.vendor.guard", "ap.security.approval.nonce",
                  "ap.security.audit.event", "ap.security.workflow.registration",
                  "account.lock_exception"):
        ids[model].update(env[model].search([("company_id", "=", company_id)], order="id").ids)
    ids["res.partner"].update(env["res.partner"].search([
        ("company_id", "=", company_id)], order="id").ids)
    ids["account.account"].update(env["account.account"].search([
        ("company_ids", "in", [company_id])], order="id").ids)
    ids["ir.sequence"].update(env["ir.sequence"].search([
        ("company_id", "in", [False, company_id])], order="id").ids)
    ids["ir.sequence.date_range"].update(env["ir.sequence.date_range"].search([
        ("sequence_id", "in", sorted(ids["ir.sequence"]))], order="id").ids)
    ids["ir.attachment"].update(env["ir.attachment"].search([
        ("company_id", "=", company_id)], order="id").ids)
    # Never enumerate arbitrary configuration values: they may contain secrets.
    ids["ir.config_parameter"].update(env["ir.config_parameter"].search([
        ("key", "=", "ir_attachment.location")], order="id").ids)
    return ids


def _closure(env, identities):
    """Expand observed relations and linked resources, never proposed keys."""
    raw = {}
    for _round in range(16):
        previous = {model: set(ids) for model, ids in identities.items()}

        def add(model, native_id):
            _require(model in identities and type(native_id) is int and native_id > 0)
            identities[model].add(native_id)
            return native_id

        for model in identities:
            raw[model] = _native_rows(env, model, identities[model])
            for row in raw[model]:
                for field, target in RELATIONS.get(model, {}).items():
                    value = row[field]
                    values = value if field in MANY_RELATIONS else [value]
                    for native_id in values:
                        if native_id is not False and native_id is not None:
                            add(target, native_id)
                for field in JSON_FIELDS & row.keys():
                    _json_relations(row[field], add, contract=field)
        # Include every bank belonging to a discovered supplier/partner, not
        # only the allowlist or currently selected recipient bank.
        identities["res.partner.bank"].update(env["res.partner.bank"].search([
            ("partner_id", "in", sorted(identities["res.partner"]))], order="id").ids)
        for model, model_field in (("ir.attachment", "res_model"), ("mail.message", "model")):
            identities[model].update(env[model].search(
                _linked_domain(model_field, identities), order="id").ids)
        _require(sum(len(ids) for ids in identities.values()) <= MAX_ROWS)
        if identities == previous:
            return raw
    raise CompanyCaptureError("native company capture closure exceeded")


def _ordinal_maps(identities):
    return {model: {native_id: index for index, native_id in enumerate(sorted(ids), 1)}
            for model, ids in identities.items()}


def _ref(maps, model, native_id):
    if native_id is False or native_id is None:
        return None
    _require(type(native_id) is int and native_id > 0 and native_id in maps[model])
    return maps[model][native_id]


def _value(name, value):
    if name in BOOLEAN_FIELDS:
        _require(type(value) is bool)
        return value
    if name in INTEGER_FIELDS:
        _require(type(value) is int)
        return value
    if name in DECIMAL_FIELDS:
        return decimal_text(value, money=(name == "amount_total"))
    if value is False or value is None:
        return None
    if type(value) is datetime:
        _require(value.tzinfo is None or value.utcoffset().total_seconds() == 0)
        return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    if type(value) is date:
        return value.isoformat()
    # Odoo Html.read deliberately returns markupsafe.Markup (a str subclass).
    # Preserve the observed text, but export only an ordinary JSON string.
    _require(isinstance(value, str))
    return str(value)


def _datetime_value(value):
    """Odoo read(load=False) returns its UTC datetime format as text."""
    if value is False or value is None:
        return None
    if type(value) is str:
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            raise CompanyCaptureError("native company capture rejected") from None
    _require(type(value) is datetime)
    return _value("datetime", value)


def _attachment_digest(env, native_id, row, filestore):
    store_fname = row["store_fname"]
    if store_fname:
        relative = PurePosixPath(store_fname)
        _require(not relative.is_absolute() and ".." not in relative.parts and
                 "\\" not in store_fname)
        _require(type(row["checksum"]) is str)
        entry = _file_digest(filestore.joinpath(*relative.parts), filestore,
                             expected_sha1=row["checksum"])
        _require(entry["size"] == row["file_size"])
        return entry["sha256"]
    value = env["ir.attachment"].browse(native_id).raw
    if value is False and row["file_size"] == 0:
        value = b""
    _require(type(value) is bytes and len(value) == row["file_size"] and
             len(value) <= MAX_FILE_BYTES)
    checksum = hashlib.sha1(value, usedforsecurity=False).hexdigest()
    _require(row["checksum"] == checksum or not value and row["checksum"] is False)
    return hashlib.sha256(value).hexdigest()


def _project(env, raw, maps, filestore):
    result = {}
    for model, rows in raw.items():
        projected = []
        for row in rows:
            item = {"ordinal": _ref(maps, model, row["id"])}
            for name in ROW_FIELDS[model]:
                if name in SPECIAL_FIELDS.get(model, set()):
                    continue
                value = row[name]
                if name in RELATIONS.get(model, {}):
                    target = RELATIONS[model][name]
                    item[name] = (sorted(_ref(maps, target, native_id) for native_id in value)
                                  if name in MANY_RELATIONS else _ref(maps, target, value))
                elif name in JSON_FIELDS:
                    item[name] = _json_relations(value, lambda target, native_id: _ref(maps, target, native_id),
                                                  contract=name)
                elif env[model]._fields[name].type == "datetime":
                    item[name] = _datetime_value(value)
                else:
                    item[name] = _value(name, value)
            if model in {"ir.attachment", "mail.message"}:
                resource_model = row["res_model" if model == "ir.attachment" else "model"]
                resource_id = row["res_id"]
                if resource_id:
                    _require(resource_model in maps)
                    item["res_ordinal"] = _ref(maps, resource_model, resource_id)
                else:
                    item["res_ordinal"] = None
            if model == "ir.attachment":
                item["content_sha256"] = _attachment_digest(env, row["id"], row, filestore)
            elif model == "mail.message":
                subtype = env["mail.message.subtype"].browse(row["subtype_id"]).exists()
                if subtype:
                    external = subtype.get_external_id().get(subtype.id)
                    _require(type(external) is str and bool(external))
                    item["subtype_ref"] = external
                else:
                    item["subtype_ref"] = None
            projected.append(item)
        result[model] = projected
    return result


def _sequence_metadata(metadata, maps):
    """Stable sequence identity excludes physical pg_class OIDs after restore."""
    result = []
    for native_name, increment in metadata:
        _require(type(native_name) is str and type(increment) is int)
        name = native_name
        match = re.fullmatch(r"ir_sequence_([0-9]+)(?:_([0-9]+))?", native_name)
        if match:
            sequence_id = int(match.group(1))
            if sequence_id not in maps["ir.sequence"]:
                continue
            name = "ir.sequence:" + str(_ref(maps, "ir.sequence", sequence_id))
            if match.group(2):
                name += "/ir.sequence.date_range:" + str(_ref(maps, "ir.sequence.date_range", int(match.group(2))))
        result.append((name, native_name, increment))
    result.sort()
    _require(len({name for name, _native, _increment in result}) == len(result))
    return result


def _postgres_sequences(env, maps):
    """Inspect PG sequences without nextval; normalize dynamic ir.sequence names."""
    from psycopg2 import sql

    env.cr.execute("""
        SELECT c.relname, p.increment_by
          FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          JOIN pg_sequences p ON p.schemaname=n.nspname AND p.sequencename=c.relname
         WHERE c.relkind='S' AND n.nspname='public' ORDER BY c.relname
    """)
    metadata = env.cr.fetchall()
    rows, identities = [], []
    for name, native_name, increment in _sequence_metadata(metadata, maps):
        env.cr.execute(sql.SQL("SELECT last_value, is_called FROM {}").format(sql.Identifier("public", native_name)))
        value, is_called = env.cr.fetchone()
        _require(type(value) is int and type(increment) is int and type(is_called) is bool)
        identities.append(len(identities) + 1)
        rows.append({"ordinal": len(rows) + 1, "name": name, "last_value": value,
                     "increment_by": increment, "is_called": is_called})
    return rows, identities


def collect(env, binding, filestore):
    """Return the agreed closed envelope; caller must persist it only locally."""
    checked = CaptureBinding.from_mapping(binding)
    _require(env.su is True)
    env.cr.execute("SHOW transaction_read_only")
    _require(env.cr.fetchone() == ("on",))
    env = env(context={"allowed_company_ids": [checked.company_id],
                       "force_company": checked.company_id, "active_test": False,
                       "lang": "en_US", "tz": "UTC"})
    company = env["res.company"].browse(checked.company_id).exists()
    _require(len(company) == 1 and company.name == checked.company_name)
    root = Path(filestore)
    files_before = filestore_projection(root)
    identities = _roots(env, checked.company_id)
    raw = _closure(env, identities)
    maps = _ordinal_maps(identities)
    records = _project(env, raw, maps, root)
    postgres, postgres_ids = _postgres_sequences(env, maps)
    records["postgres.sequence"] = postgres
    records["outbox"] = [{"ordinal": 1, "enabled": False}]
    identity_map = {model: sorted(ids) for model, ids in identities.items()}
    identity_map.update({"postgres.sequence": postgres_ids, "outbox": [1]})
    files_after = filestore_projection(root)
    _require(files_before == files_after)
    result = {"schema_version": CAPTURE_VERSION, "binding": checked.to_mapping(),
              "records": records, "identity_map": identity_map,
              "filestore": files_after,
              "state_sha256": canonical_json_sha256({"records": records, "filestore": files_after})}
    result["capture_sha256"] = capture_sha256(result)
    return result
