"""Harbor transport for the unchanged public GTM.Bench judge.

Only this checked-in wrapper runs as verifier code; candidate artifacts are data.
Native scores are exported individually, without inventing an overall GTM score.
"""

import json
import csv
import errno
import io
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
import re

TESTS = Path("/tests")
WORKSPACE = Path("/workspace")
LOGS = Path("/logs/verifier")
AGENT_LOGS = Path("/logs/agent")
OFFER_FIELDS = (
    "offer_intent_fidelity", "product_specificity", "value_proposition",
    "concision", "icp_separation",
)
ICP_FIELDS = (
    "icp_alignment", "buyer_account_specificity", "commercial_relevance",
    "gtm_actionability", "concision", "offer_separation",
)
MATCH_FIELDS = (
    "company_fit", "contact_fit", "offer_fit", "evidence_sufficiency",
    "contactability",
)
AUDIT_FIELDS = (
    "identity_resolution_normalized", "claim_support_normalized",
    "database_consistency_normalized", "contact_usability_normalized",
    "total_score",
)


def read_artifact(directory, name, limit):
    descriptor = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
    )
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("artifact is not a bounded regular file")
        content = stream.read(limit + 1)
        if len(content) > limit:
            raise ValueError("artifact exceeds byte limit")
        content.decode("utf-8")
        return content


def extract_csv(text):
    # Same CSV extraction rule as upstream runner._extract_csv.
    match = re.search(r"```csv\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    csv_text = match.group(1).strip() if match else text.strip()
    lines = [line for line in csv_text.splitlines() if line.strip()]
    header = next((index for index, line in enumerate(lines)
                   if "company" in line.lower() and "," in line), None)
    return "" if header is None else "\n".join(lines[header:]).strip() + "\n"


def message_text(message):
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        return "\n".join(part["text"] for part in message
                         if isinstance(part, dict) and part.get("type") == "text"
                         and isinstance(part.get("text"), str))
    return ""


def final_response_csv(limit):
    directory = os.open(AGENT_LOGS, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            trajectory = json.loads(read_artifact(directory, "trajectory.json", limit))
        except FileNotFoundError:
            trajectory = None
        if trajectory is not None:
            if not isinstance(trajectory, dict) or not isinstance(trajectory.get("steps"), list):
                raise ValueError("invalid ATIF trajectory")
            for step in reversed(trajectory.get("steps", [])):
                if not isinstance(step, dict):
                    raise ValueError("invalid ATIF step")
                if step.get("source") == "agent" and not step.get("tool_calls"):
                    return extract_csv(message_text(step.get("message"))).encode()
        # Harbor's Pi agent writes JSON events rather than ATIF trajectories.
        events = read_artifact(directory, "pi.txt", limit).splitlines()
        for line in reversed(events):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            message = event.get("message", {})
            if isinstance(message, dict) and event.get("type") == "message_end" and message.get("role") == "assistant":
                return extract_csv(message_text(message.get("content"))).encode()
        return b""
    finally:
        os.close(directory)


def candidate_csv(directory, task, limit, log_limit):
    for name in (task["task_id"] + ".csv", "leads.csv", "output.txt"):
        try:
            content = read_artifact(directory, name, limit)
            return extract_csv(content.decode()).encode() if name == "output.txt" else content
        except FileNotFoundError:
            continue
    return final_response_csv(log_limit)


def snapshot_artifacts(task, destination, config):
    directory = os.open(WORKSPACE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in ("offer.md", "icp.md"):
            content = read_artifact(directory, name, config["markdown_max_bytes"])
            (destination / name).write_bytes(content)
        content = candidate_csv(directory, task, config["csv_max_bytes"], config["agent_log_max_bytes"])
        if not content:
            raise ValueError("missing CSV output")
        if len(content) > config["csv_max_bytes"]:
            raise ValueError("CSV output exceeds byte limit")
        # Validate before any paid judge calls. No silent truncation of leads.
        reader = csv.DictReader(io.StringIO(content.decode()))
        if len(reader.fieldnames or []) > config["max_csv_columns"]:
            raise ValueError("CSV column count exceeds limit")
        for index, row in enumerate(reader, start=1):
            if index > config["max_lead_rows"]:
                raise ValueError("lead row count exceeds limit")
            if None in row or any(len(cell or "") > config["max_csv_cell_chars"] for cell in row.values()):
                raise ValueError("CSV row has extra columns or an oversized cell")
        (destination / "leads.csv").write_bytes(content)
    finally:
        os.close(directory)


def score(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("judge score must be numeric")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError("judge score outside native range")
    return float(value)


def native_rewards(judgments):
    rewards = {"valid_artifacts": 1.0}
    for name, fields in (("offer", OFFER_FIELDS), ("icp", ICP_FIELDS)):
        judgment = json.loads((judgments / (name + ".json")).read_text())
        for field in fields:
            rewards[name + "/" + field] = score(judgment[field]["score"], 1, 5)
    for line in (judgments / "match_quality.jsonl").read_text().splitlines():
        row = json.loads(line)
        for field in MATCH_FIELDS:
            dimension = row["judgment"]["dimension_scores"][field]
            if not isinstance(dimension["applicable"], bool):
                raise ValueError("judge applicability must be boolean")
            prefix = "match/row_" + str(row["row_index"]) + "/" + field
            rewards[prefix + "/score"] = score(dimension["score"], 1, 5)
            rewards[prefix + "/applicable"] = float(dimension["applicable"])
    for line in (judgments / "audit.jsonl").read_text().splitlines():
        row = json.loads(line)
        for field in AUDIT_FIELDS:
            name = "audit/row_" + str(row["row_index"]) + "/" + field
            rewards[name] = score(row["normalized"][field], 0, 1)
    return rewards


def write_reward(rewards):
    temporary = LOGS / "reward.pending"
    temporary.write_text(json.dumps(rewards, sort_keys=True, allow_nan=False) + "\n")
    temporary.chmod(0o644)
    temporary.replace(LOGS / "reward.json")


def run(provider=None):
    LOGS.mkdir(parents=True, exist_ok=True)
    os.chown(LOGS, 0, 0)
    # Root-owned, non-writable by the agent, readable by the Harbor host UID.
    LOGS.chmod(0o755)
    for name in ("reward.json", "reward.txt", "reward.pending", "error.json"):
        (LOGS / name).unlink(missing_ok=True)
    task = json.loads((TESTS / "record.json").read_text())
    config = json.loads((TESTS / "conversion.json").read_text())
    # Each invocation has a new private run directory: never trust agent caches,
    # manifests, artifact paths, or judgments from /workspace or a prior run.
    with tempfile.TemporaryDirectory(prefix="gtm-verifier-") as temporary:
        run_dir = Path(temporary)
        try:
            snapshot_artifacts(task, run_dir, config)
        except (OSError, ValueError, UnicodeError, csv.Error) as error:
            if isinstance(error, OSError) and error.errno not in {
                errno.ENOENT, errno.ELOOP, errno.ENOTDIR, errno.EISDIR, errno.EACCES,
            }:
                raise
            (LOGS / "error.json").write_text(json.dumps({
                "stage": "artifacts", "error_type": type(error).__name__,
                "reason": os.strerror(error.errno) if isinstance(error, OSError) else str(error)[:300],
            }))
            write_reward({"valid_artifacts": 0.0})
            return
        manifest = {"task": task, "task_id": task["task_id"], "run_id": task["task_id"]}
        (run_dir / "manifest.json").write_text(json.dumps(manifest))
        sys.path.insert(0, str(TESTS / "upstream" / "src"))
        from gtm_bench_public.judges.runner import judge_run
        from gtm_bench_public.judges.providers import OpenAIResponsesJudgeProvider

        if provider is None:
            model = os.environ.get("GTM_JUDGE_MODEL")
            if not model:
                raise RuntimeError("GTM_JUDGE_MODEL is required for the native judge")
            provider = OpenAIResponsesJudgeProvider(model=model)
        judge_run(run_dir=run_dir, provider=provider)
        judgments = run_dir / "judgments"
        rewards = native_rewards(judgments)
        # Store original judgments as data beside Harbor's reward file.
        for source in sorted(judgments.iterdir()):
            destination = LOGS / ("native_" + source.name)
            destination.unlink(missing_ok=True)
            destination.write_bytes(source.read_bytes())
            destination.chmod(0o644)
        write_reward(rewards)


if __name__ == "__main__":
    try:
        run()
    except Exception as error:
        (LOGS / "error.json").write_text(json.dumps({
            "stage": "judge",
            "error_type": f"{type(error).__name__}: {error}",
        }))
        # Judge outages and missing credentials are evaluation errors, not zero
        # agent scores. Harbor reports the missing reward as a verifier failure.
        raise SystemExit(1)
