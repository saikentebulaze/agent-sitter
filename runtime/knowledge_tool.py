from __future__ import annotations

import argparse
from pathlib import Path

from common import fail, load_json_or_yaml_like
from project_context import resolve_project_context

EVIDENCE_STATUSES = {"candidate", "verified", "disputed"}
ARCHITECTURE_STATUSES = {"current", "target", "transitional", "legacy"}
ENTRY_TYPES = {
    "fact",
    "flow",
    "decision",
    "debt",
    "critical-surface",
    "glossary",
    "open-thread",
    "watchpoint",
}
REQUIRED_FIELDS = {
    "id", "title", "type", "evidence_status", "architecture_status",
    "path", "domains", "keywords", "related",
}
OPTIONAL_FIELDS = {
    "reviewed_by",
    "reviewed_at",
    "source_change",
    "source_task",
    "source_commit",
    "validity_surface",
    "memory_key",
    "supersedes",
    "trigger_terms",
    "trigger_condition",
    "authority_sha256",
}
LIST_FIELDS = {
    "domains",
    "keywords",
    "related",
    "validity_surface",
    "supersedes",
    "trigger_terms",
}
LEGACY_FIELDS = {"kind", "status"}


def entries(project_root: Path) -> list[dict]:
    index = project_root / "knowledge" / "index.yaml"
    if not index.exists():
        fail(f"missing {index}")
    data = load_json_or_yaml_like(index)
    if data.get("version") != 1:
        fail("knowledge index version must be 1")
    result = data.get("entries") or []
    if not isinstance(result, list):
        fail("knowledge index entries must be a list")
    return result


def _valid_string_list(value: object, *, allow_empty: bool = True) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
    )


def validate_entries(
    project_root: Path,
    values: list[dict],
    *,
    require_paths: bool = True,
) -> list[str]:
    errors: list[str] = []
    ids: set[str] = set()
    by_id: dict[str, dict] = {}

    for index, entry in enumerate(values):
        label = f"entry[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label} must be a mapping")
            continue
        unknown = set(entry) - REQUIRED_FIELDS - OPTIONAL_FIELDS
        missing = REQUIRED_FIELDS - set(entry)
        if unknown:
            errors.append(f"{label} has unknown fields: {', '.join(sorted(unknown))}")
        if missing:
            errors.append(f"{label} is missing: {', '.join(sorted(missing))}")

        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id.strip():
            errors.append(f"{label} has no id")
            entry_id = f"entry[{index}]"
        elif entry_id in ids:
            errors.append(f"duplicate id: {entry_id}")
        else:
            ids.add(entry_id)
            by_id[entry_id] = entry

        title = entry.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"invalid title for {entry_id}")
        entry_type = entry.get("type")
        if entry_type not in ENTRY_TYPES:
            errors.append(f"invalid type for {entry_id}: {entry_type}")
        if entry.get("evidence_status") not in EVIDENCE_STATUSES:
            errors.append(
                f"invalid evidence_status for {entry_id}: "
                f"{entry.get('evidence_status')}"
            )
        if entry.get("architecture_status") not in ARCHITECTURE_STATUSES:
            errors.append(
                f"invalid architecture_status for {entry_id}: "
                f"{entry.get('architecture_status')}"
            )

        path_value = entry.get("path")
        if not isinstance(path_value, str) or not path_value.startswith("knowledge/"):
            errors.append(f"invalid path for {entry_id}: {path_value}")
        elif require_paths and not (project_root / path_value).is_file():
            errors.append(f"missing path for {entry_id}: {path_value}")

        for field in ("domains", "keywords", "related"):
            if not _valid_string_list(entry.get(field)):
                errors.append(f"{field} for {entry_id} must be a list of non-empty strings")
        for field in ("validity_surface", "supersedes", "trigger_terms"):
            if field in entry and not _valid_string_list(entry.get(field)):
                errors.append(f"{field} for {entry_id} must be a list of non-empty strings")

        for field in (
            "reviewed_by", "reviewed_at", "source_change", "source_task",
            "source_commit", "memory_key", "trigger_condition", "authority_sha256",
        ):
            if field in entry and (
                not isinstance(entry.get(field), str) or not str(entry.get(field)).strip()
            ):
                errors.append(f"{field} for {entry_id} must be a non-empty string")

        source_commit = entry.get("source_commit")
        validity_surface = entry.get("validity_surface")
        if bool(source_commit) != (validity_surface is not None):
            errors.append(
                f"{entry_id} must define source_commit and validity_surface together"
            )
        if isinstance(source_commit, str) and len(source_commit.strip()) < 7:
            errors.append(f"source_commit for {entry_id} is too short")
        if validity_surface is not None and not _valid_string_list(
            validity_surface, allow_empty=False
        ):
            errors.append(f"validity_surface for {entry_id} must not be empty")

        if entry_type in {"open-thread", "watchpoint"}:
            trigger_terms = entry.get("trigger_terms") or []
            trigger_condition = str(entry.get("trigger_condition") or "").strip()
            if not trigger_terms and not trigger_condition:
                errors.append(
                    f"{entry_type} {entry_id} requires trigger_terms or trigger_condition"
                )
            if not isinstance(entry.get("memory_key"), str) or not str(
                entry.get("memory_key")
            ).strip():
                errors.append(f"{entry_type} {entry_id} requires memory_key")

        if "status" in entry:
            errors.append(f"legacy status field is not allowed for {entry_id}")

    for entry in values:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("id") or "<unknown>")
        for field in ("related", "supersedes"):
            for target_id in entry.get(field, []) or []:
                if target_id not in ids:
                    errors.append(f"{entry_id} {field} unknown id: {target_id}")
                if target_id == entry_id:
                    errors.append(f"{entry_id} cannot {field} itself")

    # Explicit supersession must be unambiguous. It does not auto-merge content.
    superseded_by: dict[str, list[str]] = {}
    for entry in values:
        if not isinstance(entry, dict):
            continue
        for target_id in entry.get("supersedes", []) or []:
            superseded_by.setdefault(str(target_id), []).append(str(entry.get("id")))
    for target_id, replacers in superseded_by.items():
        if len(replacers) > 1:
            errors.append(
                f"{target_id} is superseded by multiple entries without explicit resolution: "
                + ", ".join(sorted(replacers))
            )

    return errors


def legacy_entry_labels(values: list[dict]) -> list[str]:
    labels: list[str] = []
    for index, entry in enumerate(values):
        if not isinstance(entry, dict):
            continue
        fields = sorted(set(entry) & LEGACY_FIELDS)
        if fields:
            entry_id = str(entry.get("id") or f"entry[{index}]")
            labels.append(f"{entry_id}: {', '.join(fields)}")
    return labels


def _normalize_legacy_path(value: object, index: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"entry[{index}] requires a non-empty path")
    path = value.strip().replace("\\", "/")
    segments = path.split("/")
    has_drive = len(path) >= 2 and path[1] == ":"
    if path.startswith("/") or has_drive or ".." in segments:
        raise ValueError(f"entry[{index}] legacy path requires manual mapping: {value}")
    if path.startswith("./"):
        path = path[2:]
    if path.startswith("knowledge/"):
        return path
    return f"knowledge/{path}"


def build_legacy_migration(
    values: list[dict],
    *,
    evidence_status: str,
    architecture_status: str,
) -> dict:
    if evidence_status not in EVIDENCE_STATUSES:
        raise ValueError(f"invalid evidence status: {evidence_status}")
    if architecture_status not in ARCHITECTURE_STATUSES:
        raise ValueError(f"invalid architecture status: {architecture_status}")

    migrated: list[dict] = []
    found_legacy = False
    for index, entry in enumerate(values):
        if not isinstance(entry, dict):
            raise ValueError(f"entry[{index}] must be a mapping")
        item = dict(entry)
        if "kind" in item:
            found_legacy = True
            legacy_type = item.pop("kind")
            if "type" in item and item["type"] != legacy_type:
                raise ValueError(
                    f"entry[{index}] has conflicting type and legacy kind"
                )
            if legacy_type not in ENTRY_TYPES:
                raise ValueError(
                    f"entry[{index}] legacy kind requires manual mapping: {legacy_type}"
                )
            item.setdefault("type", legacy_type)
        if "status" in item:
            found_legacy = True
            item.pop("status")

        item["path"] = _normalize_legacy_path(item.get("path"), index)
        for field in ("domains", "keywords", "related"):
            item.setdefault(field, [])
        item.setdefault("evidence_status", evidence_status)
        item.setdefault("architecture_status", architecture_status)
        migrated.append(item)

    if not found_legacy:
        raise ValueError("knowledge index has no legacy kind/status fields")

    errors = validate_entries(Path("."), migrated, require_paths=False)
    if errors:
        raise ValueError("migration candidate is not schema-valid: " + "; ".join(errors))
    return {"version": 1, "entries": migrated}


def safe_output(project_root: Path, value: Path) -> Path:
    path = value.resolve() if value.is_absolute() else (project_root / value).resolve()
    try:
        path.relative_to(project_root.resolve())
    except ValueError as error:
        raise ValueError("migration output must remain inside the project") from error
    source = (project_root / "knowledge" / "index.yaml").resolve()
    if path == source:
        raise ValueError(
            "migration-plan never overwrites knowledge/index.yaml; review a separate candidate first"
        )
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    search = subparsers.add_parser("search")
    search.add_argument("terms", nargs="+")
    show = subparsers.add_parser("show")
    show.add_argument("id")
    subparsers.add_parser("validate")
    subparsers.add_parser("diagnose")

    migration = subparsers.add_parser("migration-plan")
    migration.add_argument("--output", type=Path, required=True)
    migration.add_argument(
        "--evidence-status", choices=sorted(EVIDENCE_STATUSES), required=True
    )
    migration.add_argument(
        "--architecture-status", choices=sorted(ARCHITECTURE_STATUSES), required=True
    )
    migration.add_argument("--force", action="store_true")

    args = parser.parse_args()

    try:
        context = resolve_project_context(args.project)
    except ValueError as error:
        fail(str(error))
    values = entries(context.project_root)

    if args.cmd == "search":
        terms = [term.lower() for term in args.terms]
        scored: list[tuple[int, dict]] = []
        for entry in values:
            blob = " ".join([
                str(entry.get("id", "")),
                str(entry.get("title", "")),
                str(entry.get("type", entry.get("kind", ""))),
                str(entry.get("evidence_status", "")),
                str(entry.get("architecture_status", entry.get("status", ""))),
                str(entry.get("memory_key", "")),
                str(entry.get("trigger_condition", "")),
                *map(str, entry.get("domains", []) or []),
                *map(str, entry.get("keywords", []) or []),
                *map(str, entry.get("trigger_terms", []) or []),
            ]).lower()
            score = sum(1 for term in terms if term in blob)
            if score:
                scored.append((score, entry))
        for _, entry in sorted(scored, key=lambda item: (-item[0], item[1].get("id", ""))):
            print(
                f"{entry.get('id')}\t"
                f"{entry.get('evidence_status', 'legacy')}\t"
                f"{entry.get('architecture_status', entry.get('status', 'legacy'))}\t"
                f"{entry.get('path')}\t"
                f"{entry.get('title')}"
            )
        if not scored:
            print("no matching knowledge entries")
        return

    if args.cmd == "show":
        entry = next((item for item in values if item.get("id") == args.id), None)
        if not entry:
            fail(f"unknown id: {args.id}")
        print((context.project_root / entry["path"]).read_text(encoding="utf-8"))
        return

    errors = validate_entries(context.project_root, values)

    if args.cmd == "diagnose":
        legacy = legacy_entry_labels(values)
        if not errors:
            print(f"knowledge_index: valid ({len(values)} entries)")
            return
        print("knowledge_index: incompatible (diagnostic only; exit code 0)")
        for label in legacy:
            print(f"LEGACY: {label}")
        for error in errors:
            print(f"ISSUE: {error}")
        if legacy:
            print(
                "next: run migration-plan with explicit --evidence-status and "
                "--architecture-status; the source index will not be overwritten"
            )
        return

    if args.cmd == "migration-plan":
        try:
            candidate = build_legacy_migration(
                values,
                evidence_status=args.evidence_status,
                architecture_status=args.architecture_status,
            )
            output = safe_output(context.project_root, args.output)
        except ValueError as error:
            fail(str(error))
        if output.exists() and not args.force:
            fail(f"migration output already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        import yaml

        output.write_text(
            yaml.safe_dump(candidate, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        print("migration defaults: missing domains/keywords/related -> []")
        print("migration path rule: relative legacy paths -> knowledge/<legacy-path>")
        print(output.relative_to(context.project_root))
        return

    if errors:
        for error in errors:
            print("ERROR:", error)
        raise SystemExit(1)
    print(f"knowledge_index: valid ({len(values)} entries)")


if __name__ == "__main__":
    main()
