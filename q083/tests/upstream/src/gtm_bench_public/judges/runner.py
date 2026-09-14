from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from gtm_bench_public.judges.providers import JudgeProvider
from gtm_bench_public.scoring import normalize_audit_scores


def judge_run(*, run_dir: str | Path, provider: JudgeProvider) -> dict[str, Any]:
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    task = manifest["task"]
    offer_md = _artifact_path(run_dir, manifest, "offer_file", "offer.md").read_text(
        encoding="utf-8"
    )
    icp_md = _artifact_path(run_dir, manifest, "icp_file", "icp.md").read_text(
        encoding="utf-8"
    )
    judgments_dir = run_dir / "judgments"
    judgments_dir.mkdir(exist_ok=True)

    offer_judgment = _load_or_judge_json(
        judgments_dir / "offer.json",
        provider=provider,
        prompt=_judge_prompt("offer_judge.md"),
        packet={"task": task, "offer_markdown": offer_md},
    )

    icp_judgment = _load_or_judge_json(
        judgments_dir / "icp.json",
        provider=provider,
        prompt=_judge_prompt("icp_judge.md"),
        packet={"task": task, "offer_markdown": offer_md, "icp_markdown": icp_md},
    )

    source_headers, rows = _read_csv(_csv_path(run_dir, manifest))
    match_path = judgments_dir / "match_quality.jsonl"
    audit_path = judgments_dir / "audit.jsonl"
    completed_match_rows = _existing_row_indexes(match_path)
    with match_path.open("a", encoding="utf-8") as handle:
        for index, row in enumerate(rows, start=1):
            if index in completed_match_rows:
                continue
            judgment = provider.judge_json(
                prompt=_judge_prompt("match_quality_judge.md"),
                packet={
                    "task": task,
                    "artifacts": {
                        "offer_markdown": offer_md,
                        "icp_markdown": icp_md,
                    },
                    "candidate_row": row,
                    "adapter_evidence": {
                        "status": "missing_identifiers",
                        "evidence_summary": "No private evidence used for this web-only run.",
                        "source_types": [],
                        "raw_private_data_included": False,
                    },
                },
            )
            handle.write(
                json.dumps({"row_index": index, "row": row, "judgment": judgment}, sort_keys=True)
                + "\n"
            )
    completed_audit_rows = _existing_row_indexes(audit_path)
    with audit_path.open("a", encoding="utf-8") as handle:
        for index, row in enumerate(rows, start=1):
            if index in completed_audit_rows:
                continue
            judgment = provider.judge_json(
                prompt=_judge_prompt("audit_judge.md"),
                packet={
                    "task": task,
                    "source_headers": source_headers,
                    "candidate_row": row,
                    "artifacts": {
                        "offer_markdown": offer_md,
                        "icp_markdown": icp_md,
                    },
                    "adapter_evidence": {
                        "status": "missing_identifiers",
                        "evidence_summary": "No private evidence used for this web-only run.",
                        "source_types": [],
                        "raw_private_data_included": False,
                    },
                },
            )
            handle.write(
                json.dumps(
                    {
                        "row_index": index,
                        "row": row,
                        "judgment": judgment,
                        "normalized": normalize_audit_scores(judgment),
                    },
                    sort_keys=True,
                )
                + "\n"
            )

    summary = {
        "run_id": manifest.get("run_id"),
        "row_count": len(rows),
        "match_quality_judgment_count": len(rows),
        "audit_judgment_count": len(rows),
        "judgments_dir": str(judgments_dir),
    }
    (judgments_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    return summary


def _load_or_judge_json(
    path: Path,
    *,
    provider: JudgeProvider,
    prompt: str,
    packet: dict[str, Any],
) -> dict[str, Any]:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    judgment = provider.judge_json(prompt=prompt, packet=packet)
    path.write_text(json.dumps(judgment, indent=2, sort_keys=True), encoding="utf-8")
    return judgment


def _existing_row_indexes(path: Path) -> set[int]:
    if not path.is_file():
        return set()
    indexes: set[int] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            indexes.add(int(payload["row_index"]))
        except (KeyError, TypeError, ValueError):
            continue
    return indexes


def _artifact_path(run_dir: Path, manifest: dict[str, Any], key: str, fallback: str) -> Path:
    value = (manifest.get("artifacts") or {}).get(key)
    if isinstance(value, str) and value:
        path = Path(value)
        if path.is_file():
            return path
        candidate = run_dir / value
        if candidate.is_file():
            return candidate
    return run_dir / fallback


def _csv_path(run_dir: Path, manifest: dict[str, Any]) -> Path:
    artifacts = manifest.get("artifacts") or {}
    for key in ("run_csv_file", "leads_csv"):
        value = artifacts.get(key)
        if not isinstance(value, str) or not value:
            continue
        path = Path(value)
        if path.is_file():
            return path
        candidate = run_dir / value
        if candidate.is_file():
            return candidate

    task_id = str(manifest.get("task_id") or (manifest.get("task") or {}).get("task_id") or "")
    if task_id:
        candidate = run_dir / f"{task_id}.csv"
        if candidate.is_file():
            return candidate
    return run_dir / "leads.csv"


def _judge_prompt(name: str) -> str:
    root = Path(__file__).resolve().parents[3]
    return (root / "prompts" / "judges" / name).read_text(encoding="utf-8")


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        return [], []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [_clean_csv_row(row) for row in reader]


def _clean_csv_row(row: dict[Any, Any]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in row.items():
        if key is None:
            if isinstance(value, list) and value:
                cleaned["_extra_columns"] = " | ".join(str(item) for item in value)
            elif value not in (None, ""):
                cleaned["_extra_columns"] = str(value)
            continue
        cleaned[str(key)] = "" if value is None else str(value)
    return cleaned
