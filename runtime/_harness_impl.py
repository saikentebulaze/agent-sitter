from __future__ import annotations

import argparse
import difflib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from artifact_consistency import (
    file_sha256,
    git_diff_sha256,
    symbol_warnings,
    validate_markdown_links,
)
from knowledge_tool import validate_entries
from project_context import ProjectContext, resolve_project_context
from review_transaction import (
    ReviewTransactionError,
    atomic_write_yaml,
    record_review,
)


REVIEWERS = {
    "maintainer": {
        "agent": "maintainer_reviewer",
        "model": "gpt-5.6-terra",
        "tier": "terra",
    },
    "deep": {
        "agent": "deep_reviewer",
        "model": "gpt-5.6-sol",
        "tier": "sol",
    },
}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_yaml(path: Path) -> dict:
    if not path.is_file():
        fail(f"missing file: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        fail(f"expected YAML mapping: {path}")
    return data


def write_yaml(path: Path, data: dict) -> None:
    try:
        atomic_write_yaml(path, data)
    except ReviewTransactionError as error:
        fail(str(error))


def resolve_change(context: ProjectContext, value: str) -> Path:
    raw = Path(value)
    candidates = []
    if raw.is_absolute() or len(raw.parts) > 1:
        candidates.append(raw)
    else:
        candidates.extend([
            context.project_root / "changes" / "active" / value,
            context.project_root / "changes" / "archive" / value,
        ])
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_dir() and (resolved / "change.yaml").is_file():
            try:
                resolved.relative_to(context.project_root)
            except ValueError:
                fail(f"change is outside project: {resolved}")
            return resolved
    fail(f"change not found: {value}")


def project_relative(context: ProjectContext, path: Path) -> str:
    try:
        return path.resolve().relative_to(context.project_root).as_posix()
    except ValueError:
        fail(f"path is outside project: {path}")


def safe_project_path(context: ProjectContext, value: str, label: str) -> Path:
    path = (context.project_root / value).resolve()
    try:
        path.relative_to(context.project_root)
    except ValueError:
        fail(f"{label} escapes project: {value}")
    return path


def run_change_validator(context: ProjectContext, change: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(context.package_root / "runtime" / "validate_change.py"),
            str(change),
        ],
        cwd=context.project_root,
    )
    if result.returncode:
        raise SystemExit(result.returncode)


def command_status(context: ProjectContext, change: Path) -> None:
    data = load_yaml(change / "change.yaml")
    summary = {
        "id": data.get("id") or change.name,
        "location": project_relative(context, change),
        "status": data.get("status"),
        "risk": data.get("risk"),
        "implementation_complete": (data.get("completion") or {}).get("implementation_complete"),
        "ready_for_user_review": (data.get("completion") or {}).get("ready_for_user_review"),
        "user_review": (data.get("user_review") or {}).get("status"),
        "independent_review": (data.get("review") or {}).get("status"),
        "verification": (data.get("verification") or {}).get("status"),
        "knowledge_sync": (data.get("knowledge_sync") or {}).get("status"),
        "archive_blockers": (data.get("archive") or {}).get("blockers") or [],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def command_validate(context: ProjectContext, change: Path, strict_symbols: bool) -> None:
    run_change_validator(context, change)

    link_errors = validate_markdown_links(change, context.project_root)
    if link_errors:
        for error in link_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)

    index = context.project_root / "knowledge" / "index.yaml"
    if index.is_file():
        data = load_yaml(index)
        values = data.get("entries") or []
        errors = validate_entries(context.project_root, values)
        if errors:
            for error in errors:
                print(f"ERROR: knowledge index: {error}", file=sys.stderr)
            raise SystemExit(1)

    warnings = symbol_warnings(change, context.project_root)
    for warning in warnings:
        print(f"WARNING: {warning}")
    if strict_symbols and warnings:
        raise SystemExit(2)
    print("change_consistency: valid")


def command_review_packet(
    context: ProjectContext,
    change: Path,
    reviewer_name: str,
    elevated_authorization_ref: str | None,
) -> None:
    reviewer = dict(REVIEWERS[reviewer_name])
    if reviewer_name == "deep" and not elevated_authorization_ref:
        fail("deep review requires --elevated-authorization-ref")

    packet_path = change / "review-request.yaml"
    if packet_path.exists():
        pending = load_yaml(packet_path)
        fail(
            "pending review request already exists for round "
            f"{pending.get('round')}; record or remove it before creating another"
        )

    data = load_yaml(change / "change.yaml")
    next_round = len(data.get("review_history") or []) + 1
    reviews_dir = change / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    output = reviews_dir / f"round-{next_round}.md"
    if output.exists():
        fail(f"review output already exists without matching history: {output}")
    packet = {
        "change_id": data.get("id") or change.name,
        "round": next_round,
        "reviewer": reviewer,
        "method": "native-subagent",
        "output_ref": project_relative(context, output),
        "elevated_authorization_ref": elevated_authorization_ref,
        "input_snapshot": {
            "design_sha256": file_sha256(change / "design.md"),
            "tasks_sha256": file_sha256(change / "tasks.md"),
            "diff_sha256": git_diff_sha256(context.project_root),
            "verification_sha256": file_sha256(change / "verification.md"),
        },
        "inputs": {
            "proposal": project_relative(context, change / "proposal.md"),
            "design": project_relative(context, change / "design.md"),
            "tasks": project_relative(context, change / "tasks.md"),
            "verification": project_relative(context, change / "verification.md"),
            "change_yaml": project_relative(context, change / "change.yaml"),
        },
        "instructions": (
            "Spawn the named native read-only reviewer and wait for completion. The reviewer "
            "must only return its findings and must not write project files. Save the exact "
            "returned text as a temporary project artifact, then call harness record-review. "
            "Do not edit review metadata or review_history by hand. This packet does not "
            "itself constitute a completed review."
        ),
    }
    write_yaml(packet_path, packet)
    print(project_relative(context, packet_path))


def command_record_review(
    context: ProjectContext,
    change: Path,
    artifact: Path,
    architecture: str,
    scope: str,
    numerical_evidence: str,
    evidence_ref: str,
    remediation_route: str | None,
) -> None:
    try:
        output, already_recorded = record_review(
            context,
            change,
            artifact,
            architecture=architecture,
            scope=scope,
            numerical_evidence=numerical_evidence,
            evidence_ref=evidence_ref,
            remediation_route=remediation_route,
        )
    except ReviewTransactionError as error:
        fail(str(error))
    prefix = "already recorded" if already_recorded else "recorded"
    print(f"{prefix}: {project_relative(context, output)}")


def knowledge_entries(data: dict) -> list[dict]:
    sync = data.get("knowledge_sync") or {}
    values = sync.get("entries") or []
    if not isinstance(values, list) or not values:
        fail("knowledge_sync.entries has no candidates")
    for index, entry in enumerate(values):
        if not isinstance(entry, dict):
            fail(f"knowledge_sync.entries[{index}] must be a mapping")
        for key in ("id", "action", "candidate", "target", "index_entry"):
            if key not in entry:
                fail(f"knowledge_sync.entries[{index}] is missing {key}")
        if entry["action"] not in {"add", "replace"}:
            fail(f"invalid knowledge action: {entry['action']}")
        if not isinstance(entry["index_entry"], dict):
            fail(f"knowledge_sync.entries[{index}].index_entry must be a mapping")
    return values


def command_render_knowledge(context: ProjectContext, change: Path) -> None:
    data = load_yaml(change / "change.yaml")
    entries = knowledge_entries(data)
    diff_lines: list[str] = []
    for entry in entries:
        candidate = safe_project_path(context, str(entry["candidate"]), "knowledge candidate")
        target = safe_project_path(context, str(entry["target"]), "knowledge target")
        if not candidate.is_file():
            fail(f"knowledge candidate does not exist: {candidate}")
        if not str(entry["target"]).startswith("knowledge/"):
            fail(f"knowledge target must be under knowledge/: {entry['target']}")
        before = target.read_text(encoding="utf-8").splitlines(keepends=True) if target.exists() else []
        after = candidate.read_text(encoding="utf-8").splitlines(keepends=True)
        diff_lines.extend(difflib.unified_diff(
            before,
            after,
            fromfile=str(entry["target"]) if target.exists() else "/dev/null",
            tofile=str(entry["target"]),
        ))
        if diff_lines and not diff_lines[-1].endswith("\n"):
            diff_lines[-1] += "\n"

    output = change / "knowledge-review.diff"
    output.write_text("".join(diff_lines) or "# No content differences\n", encoding="utf-8")
    sync = data.setdefault("knowledge_sync", {})
    sync["status"] = "candidate"
    sync["candidate_ref"] = project_relative(context, change / "knowledge-sync.md")
    sync["rendered_diff_ref"] = project_relative(context, output)
    write_yaml(change / "change.yaml", data)
    print(project_relative(context, output))


def command_promote_knowledge(
    context: ProjectContext,
    change: Path,
    reviewed_by: str,
    evidence: str,
) -> None:
    data = load_yaml(change / "change.yaml")
    entries = knowledge_entries(data)
    sync = data.get("knowledge_sync") or {}
    if sync.get("status") != "reviewed":
        fail("knowledge_sync.status must be reviewed before promotion")
    for key in ("reviewed_by", "reviewed_at", "review_evidence"):
        value = sync.get(key)
        if not isinstance(value, str) or not value.strip():
            fail(f"knowledge_sync.{key} must be recorded before promotion")
    if reviewed_by != sync["reviewed_by"]:
        fail("--reviewed-by must match knowledge_sync.reviewed_by")
    if evidence != sync["review_evidence"]:
        fail("--evidence must match knowledge_sync.review_evidence")

    rendered = sync.get("rendered_diff_ref")
    if not isinstance(rendered, str) or not safe_project_path(
        context, rendered, "rendered knowledge diff"
    ).is_file():
        fail("render-knowledge-diff must be completed before promotion")

    index_path = context.project_root / "knowledge" / "index.yaml"
    if index_path.exists():
        index_data = load_yaml(index_path)
    else:
        index_data = {"version": 1, "entries": []}
    if index_data.get("version") != 1 or not isinstance(index_data.get("entries"), list):
        fail("knowledge/index.yaml has an unsupported structure")

    next_entries = [dict(item) for item in index_data["entries"]]
    by_id = {item.get("id"): index for index, item in enumerate(next_entries)}
    staged_files: list[tuple[Path, str]] = []

    for entry in entries:
        entry_id = str(entry["id"])
        candidate = safe_project_path(context, str(entry["candidate"]), "knowledge candidate")
        target = safe_project_path(context, str(entry["target"]), "knowledge target")
        if not candidate.is_file():
            fail(f"knowledge candidate does not exist: {candidate}")
        if not str(entry["target"]).startswith("knowledge/"):
            fail(f"knowledge target must be under knowledge/: {entry['target']}")
        if entry["action"] == "add" and (entry_id in by_id or target.exists()):
            fail(f"knowledge add conflicts with existing entry/path: {entry_id}")
        if entry["action"] == "replace" and entry_id not in by_id:
            fail(f"knowledge replace references unknown entry: {entry_id}")

        index_entry = dict(entry["index_entry"])
        index_entry.update({
            "id": entry_id,
            "path": str(entry["target"]),
            "reviewed_by": reviewed_by,
            "reviewed_at": sync["reviewed_at"],
            "source_change": data.get("id") or change.name,
        })
        if entry_id in by_id:
            next_entries[by_id[entry_id]] = index_entry
        else:
            by_id[entry_id] = len(next_entries)
            next_entries.append(index_entry)
        staged_files.append((target, candidate.read_text(encoding="utf-8")))

    validation_errors = validate_entries(context.project_root, next_entries, require_paths=False)
    if validation_errors:
        for error in validation_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)

    for target, content in staged_files:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(index_path, {"version": 1, "entries": next_entries})

    post_errors = validate_entries(context.project_root, next_entries)
    if post_errors:
        fail("promoted knowledge failed post-write validation: " + "; ".join(post_errors))

    sync = data.setdefault("knowledge_sync", {})
    sync["status"] = "promoted"
    write_yaml(change / "change.yaml", data)
    print(f"promoted {len(entries)} knowledge entries")


def command_archive(context: ProjectContext, change: Path, dry_run: bool) -> None:
    command = [
        sys.executable,
        str(context.package_root / "runtime" / "archive_change.py"),
        str(change),
        "--project",
        str(context.project_root),
    ]
    if dry_run:
        command.append("--dry-run")
    raise SystemExit(subprocess.run(command, cwd=context.project_root).returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified Sitter Harness closure commands")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("status", "validate-change", "review", "render-knowledge-diff", "archive"):
        command = subparsers.add_parser(name)
        command.add_argument("change")
    subparsers.choices["validate-change"].add_argument("--strict-symbols", action="store_true")
    subparsers.choices["review"].add_argument(
        "--reviewer", choices=sorted(REVIEWERS), default="maintainer"
    )
    subparsers.choices["review"].add_argument("--elevated-authorization-ref")
    subparsers.choices["archive"].add_argument("--dry-run", action="store_true")

    record = subparsers.add_parser("record-review")
    record.add_argument("change")
    record.add_argument("--artifact", type=Path, required=True)
    for name in ("architecture", "scope", "numerical-evidence"):
        record.add_argument(f"--{name}", choices=("pass", "warn", "block"), required=True)
    record.add_argument("--evidence-ref", required=True)
    record.add_argument(
        "--remediation-route",
        choices=("implementation", "awaiting-production-design"),
    )

    promote = subparsers.add_parser("promote-knowledge")
    promote.add_argument("change")
    promote.add_argument("--reviewed-by", required=True)
    promote.add_argument("--evidence", required=True)

    args = parser.parse_args()
    try:
        context = resolve_project_context(args.project)
    except ValueError as error:
        fail(str(error))
    change = resolve_change(context, args.change)

    if args.command == "status":
        command_status(context, change)
    elif args.command == "validate-change":
        command_validate(context, change, args.strict_symbols)
    elif args.command == "review":
        command_review_packet(
            context,
            change,
            args.reviewer,
            args.elevated_authorization_ref,
        )
    elif args.command == "record-review":
        command_record_review(
            context,
            change,
            args.artifact,
            args.architecture,
            args.scope,
            args.numerical_evidence,
            args.evidence_ref,
            args.remediation_route,
        )
    elif args.command == "render-knowledge-diff":
        command_render_knowledge(context, change)
    elif args.command == "promote-knowledge":
        command_promote_knowledge(context, change, args.reviewed_by, args.evidence)
    elif args.command == "archive":
        command_archive(context, change, args.dry_run)


if __name__ == "__main__":
    main()
