"""Gera propostas reais do DeepSeek para runs do piloto (estágio LLM isolado).

Não toca no Odoo e não decide sucesso de ataque. As saídas ficam em .runtime
(ignorado pelo Git) e contêm texto de proposta; nunca a chave. Cada chamada é
confirmada por --confirm-real-calls, que deve ser igual ao número planejado.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway/src"))

from tcc_gateway.pilot_dataset import read_pilot_cohort  # noqa: E402
from tcc_gateway.pilot_proposal_batch import batch_sha256, build_batch  # noqa: E402
from tcc_gateway.state import canonical_json_bytes  # noqa: E402

KEY = ROOT / ".runtime/secrets/deepseek_api_key"
PROJECT = "tcc-pilot-proposals"
COMPOSE = ["docker", "--context", "desktop-linux", "compose", "--project-name", PROJECT,
           "--env-file", str(ROOT / ".env.example"), "--profile", "g3c"]


def run(args, **kwargs):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", **kwargs)


def must(result, message):
    if result.returncode != 0:
        raise SystemExit(message)
    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cohort-root", type=Path, required=True)
    p.add_argument("--cohort-sha256", required=True)
    p.add_argument("--out-root", type=Path, required=True, help="diretório novo sob .runtime")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--repetitions", type=int, default=3)
    p.add_argument("--roles", nargs="+", default=["benign", "adversarial"])
    p.add_argument("--conditions", nargs="+", default=["C0", "C1"])
    p.add_argument("--limit", type=int)
    p.add_argument("--confirm-real-calls", type=int, required=True)
    p.add_argument("--allow-dirty", action="store_true")
    a = p.parse_args(argv)

    out = a.out_root.resolve()
    if ROOT / ".runtime" not in out.parents:
        raise SystemExit("out-root precisa estar sob .runtime")
    if out.exists():
        raise SystemExit("out-root já existe; não reutilizar resultados")
    if not KEY.is_file() or KEY.stat().st_size < 20:
        raise SystemExit("chave DeepSeek local ausente")
    must(run(["git", "check-ignore", "--quiet", "--", str(KEY)]), "chave não está ignorada pelo Git")
    status = run(["git", "status", "--porcelain", "--untracked-files=normal"]).stdout.strip()
    if status and not a.allow_dirty:
        raise SystemExit("árvore Git suja; commite antes de chamadas reais")
    commit = run(["git", "rev-parse", "HEAD"]).stdout.strip()

    cohort = read_pilot_cohort(a.cohort_root.resolve(), a.cohort_sha256)
    batch = build_batch(cohort, repetitions=a.repetitions, seed=a.seed,
                        roles=tuple(a.roles), conditions=tuple(a.conditions))
    planned = batch["item_count"] if a.limit is None else min(a.limit, batch["item_count"])
    if a.confirm_real_calls != planned:
        raise SystemExit(f"confirmação diverge: planejadas {planned} chamadas reais")

    (out / "in").mkdir(parents=True)
    (out / "out").mkdir()
    (out / "in/batch.json").write_bytes(canonical_json_bytes(batch) + b"\n")
    started = datetime.now(timezone.utc).isoformat()
    up = False
    try:
        must(run(COMPOSE + ["build", "llm-client-g3c", "g3c-runner", "egress-proxy"]), "build falhou")
        must(run(COMPOSE + ["up", "-d", "--wait", "egress-proxy", "llm-client-g3c"]), "serviços não ficaram saudáveis")
        up = True
        env = ["-e", "TCC_BATCH_FILE=/batch/batch.json", "-e", "TCC_BATCH_OUT=/results"]
        if a.limit is not None:
            env += ["-e", f"TCC_BATCH_LIMIT={a.limit}"]
        batch_mount = str(out / "in").replace("\\", "/")
        out_mount = str(out / "out").replace("\\", "/")
        result = run(COMPOSE + ["run", "--rm", "--no-deps", "-v", f"{batch_mount}:/batch:ro",
                                "-v", f"{out_mount}:/results", *env, "g3c-runner",
                                "python", "-m", "tcc_gateway.pilot_proposal_batch"])
        summary_line = next((l for l in result.stdout.splitlines() if l.startswith("{")), "{}")
        proxy = run(COMPOSE + ["logs", "--no-color", "egress-proxy"]).stdout
        client = run(COMPOSE + ["logs", "--no-color", "llm-client-g3c"]).stdout
        key = KEY.read_text(encoding="utf-8").strip()
        outputs = "".join(f.read_text(encoding="utf-8") for f in (out / "out").glob("*.json"))
        leaked = any(key in blob for blob in (result.stdout, result.stderr, proxy, client, outputs))
        record = {
            "schema_version": "pilot-proposals-run/v1", "git_commit": commit,
            "dirty_tree": bool(status), "started_utc": started,
            "finished_utc": datetime.now(timezone.utc).isoformat(),
            "batch_sha256": batch_sha256(batch), "seed": a.seed, "planned_calls": planned,
            "container_exit_code": result.returncode, "summary": json.loads(summary_line),
            "proxy_allowed_tunnels": proxy.count("proxy_event=allow"),
            "secret_found_in_logs_or_outputs": leaked, "scientific_run": False,
            "result_files": len(list((out / "out").glob("*.json"))),
        }
        (out / "run.json").write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(record, indent=2, sort_keys=True))
        if leaked:
            raise SystemExit("SEGREDO detectado em logs/saídas; revogar a chave")
        return 0 if result.returncode == 0 else 1
    finally:
        if up:
            run(COMPOSE + ["down", "--remove-orphans"])


if __name__ == "__main__":
    raise SystemExit(main())
