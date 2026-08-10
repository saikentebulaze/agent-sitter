from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


VALIDITY_SURFACE = ["src/state/session.py"]


def run(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=check,
    )


def write(repo: Path, relative: str, content: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def commit(repo: Path, message: str) -> str:
    run(repo, "add", "-A")
    run(repo, "commit", "-m", message)
    return run(repo, "rev-parse", "HEAD").stdout.strip()


def create_fixture(destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    run(destination, "init")
    run(destination, "config", "user.email", "v6-fixture@example.invalid")
    run(destination, "config", "user.name", "V6 Fixture")

    write(destination, "src/state/session.py", "COMMITTED = 1\n")
    write(destination, "docs/notes.md", "root\n")
    root = commit(destination, "fixture root")

    run(destination, "checkout", "-b", "memory-source")
    write(destination, "src/state/session.py", "COMMITTED = 2\n")
    source = commit(destination, "memory source A")
    run(destination, "tag", "memory-source-A", source)

    run(destination, "checkout", "-b", "fresh-unrelated")
    write(destination, "docs/notes.md", "unrelated change\n")
    fresh_head = commit(destination, "unrelated change")

    run(destination, "checkout", "memory-source")
    run(destination, "checkout", "-b", "suspect-related")
    write(destination, "src/state/session.py", "COMMITTED = 3\n")
    suspect_head = commit(destination, "related state change")

    run(destination, "checkout", root)
    run(destination, "checkout", "-b", "unknown-divergent")
    write(destination, "src/other.py", "VALUE = 7\n")
    unknown_head = commit(destination, "divergent history")

    run(destination, "checkout", "fresh-unrelated")
    manifest = {
        "schema_version": 1,
        "scenario": "C6-memory-evolution",
        "source_commit": source,
        "validity_surface": VALIDITY_SURFACE,
        "cases": [
            {"name": "unrelated-commit", "head": fresh_head, "expected": "fresh"},
            {"name": "validity-surface-commit", "head": suspect_head, "expected": "suspect"},
            {"name": "source-not-ancestor", "head": unknown_head, "expected": "unknown"},
            {
                "name": "working-tree-related",
                "head": fresh_head,
                "working_tree_change": "src/state/session.py",
                "expected": "suspect",
            },
        ],
        "semantics": {
            "fresh": "no invalidating repository evolution detected; not reverified",
            "suspect": "relevant committed or working-tree change intersects validity surface",
            "unknown": "source commit is not an ancestor of current head",
        },
    }
    (destination / "memory-fixture.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def changed_paths(repo: Path, *args: str) -> set[str]:
    result = run(repo, "diff", "--name-only", *args)
    return {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}


def oracle_status(repo: Path, source_commit: str, validity_surface: list[str]) -> str:
    ancestor = run(repo, "merge-base", "--is-ancestor", source_commit, "HEAD", check=False)
    if ancestor.returncode != 0:
        return "unknown"
    validity = {value.replace("\\", "/") for value in validity_surface}
    committed = changed_paths(repo, f"{source_commit}..HEAD")
    working = changed_paths(repo)
    staged = changed_paths(repo, "--cached")
    if validity & (committed | working | staged):
        return "suspect"
    return "fresh"


def exercise_fixture(repo: Path) -> dict:
    manifest = json.loads((repo / "memory-fixture.json").read_text(encoding="utf-8"))
    source = str(manifest["source_commit"])
    validity = list(manifest["validity_surface"])
    observed = []

    for case in manifest["cases"]:
        run(repo, "reset", "--hard")
        run(repo, "clean", "-fd")
        run(repo, "checkout", str(case["head"]))
        working = case.get("working_tree_change")
        if working:
            path = repo / str(working)
            path.write_text(path.read_text(encoding="utf-8") + "# dirty\n", encoding="utf-8")
        status = oracle_status(repo, source, validity)
        observed.append({
            "name": case["name"],
            "expected": case["expected"],
            "observed": status,
            "match": status == case["expected"],
        })

    return {"cases": observed, "oracle_matches": all(item["match"] for item in observed)}


def main() -> None:
    parser = argparse.ArgumentParser(description="V6 C6 memory evolution Git fixture")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("destination", type=Path)
    exercise = subparsers.add_parser("exercise")
    exercise.add_argument("repository", type=Path)
    args = parser.parse_args()

    if args.command == "create":
        print(json.dumps(create_fixture(args.destination), indent=2))
    else:
        print(json.dumps(exercise_fixture(args.repository), indent=2))


if __name__ == "__main__":
    main()
