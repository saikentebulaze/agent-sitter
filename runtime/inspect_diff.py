from __future__ import annotations
import argparse, re
from common import run_git, fail

PATTERNS = {
    "test_assertion": re.compile(r"^\+.*\b(?:EXPECT_|ASSERT_|REQUIRE|CHECK)"),
    "tolerance": re.compile(r"^\+.*(?:toleran|epsilon|eps\b|1e-\d+|1\.0e-\d+)", re.I),
    "catch": re.compile(r"^\+\s*catch\s*\("),
    "fallback": re.compile(r"^\+.*\b(?:fallback|default value|continue on error|ignore error)\b", re.I),
    "member_state": re.compile(r"^\+\s*(?:mutable\s+)?(?:std::|[A-Za-z_][\w:<> ,*&]+)\s+[A-Za-z_]\w*_\s*(?:[;={])"),
    "class": re.compile(r"^\+\s*(?:class|struct)\s+[A-Za-z_]\w*"),
    "experiment_marker": re.compile(r"^\+.*\b(?:EXPERIMENT|DEBUG_ONLY|TEMP(?:ORARY)?|TRIAL_ONLY)\b", re.I),
    "debug_output": re.compile(r"^\+.*(?:std::cout|std::cerr|printf\s*\(|qDebug\s*\()", re.I),
    "compile_switch": re.compile(r"^\+\s*#\s*(?:if|ifdef|ifndef).*(?:EXPERIMENT|DEBUG|TEMP|TRIAL)", re.I),
}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="HEAD")
    ap.add_argument("--staged", action="store_true")
    args = ap.parse_args()

    git_args = ["diff", "--no-ext-diff", "--unified=0"]
    git_args.append("--cached" if args.staged else args.base)

    try:
        diff = run_git(git_args)
    except RuntimeError as e:
        fail(str(e))

    changed, current = [], ""
    findings = {k: [] for k in PATTERNS}

    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            changed.append(current)
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for name, pattern in PATTERNS.items():
            if pattern.search(line):
                findings[name].append((current, line[1:200]))

    print("changed_files:")
    for f in sorted(set(changed)):
        print(f"- {f}")

    print("risk_triggers:")
    any_found = False
    for name, items in findings.items():
        if not items:
            continue
        any_found = True
        print(f"- {name}: {len(items)}")
        for f, snippet in items[:8]:
            print(f"  - {f}: {snippet.strip()}")

    if not any_found:
        print("- none_detected")

    residue = sum(len(findings[k]) for k in ("experiment_marker", "debug_output", "compile_switch"))
    print(f"investigation_residue_candidates: {residue}")
    print("note: heuristic output classifies evidence only; absence is not proof of low risk or no semantic change")
    print("note: model judgment may raise risk above script triggers and must not lower a reported minimum")

if __name__ == "__main__":
    main()
