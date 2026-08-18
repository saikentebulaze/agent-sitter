from __future__ import annotations

import re

import yaml


REVIEW_STATUS = {"pass", "warn", "block"}
REMEDIATION_ROUTES = {"implementation", "awaiting-production-design"}
_TAIL = re.compile(
    r"(?ms)(?:^|\n)```ya?ml\s*\n(?P<body>.*?\nsitter_review:\s*\n.*?)\n```\s*$"
)


class ReviewVerdictError(ValueError):
    pass


def _candidate_yaml(text: str) -> str:
    blocks = re.findall(r"(?ms)```ya?ml\s*\n(.*?)\n```", text)
    for block in reversed(blocks):
        if re.search(r"(?m)^sitter_review\s*:", block):
            return block
    match = re.search(r"(?ms)(^sitter_review\s*:\s*\n.*)\Z", text.strip())
    if match:
        return match.group(1)
    raise ReviewVerdictError("reviewer output has no sitter_review YAML verdict tail")


def parse_review_verdict(text: str) -> dict[str, str | None]:
    if not text.strip():
        raise ReviewVerdictError("reviewer output is empty")
    raw = _candidate_yaml(text)
    try:
        payload = yaml.safe_load(raw)
    except yaml.YAMLError as error:
        raise ReviewVerdictError(f"invalid sitter_review YAML: {error}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("sitter_review"), dict):
        raise ReviewVerdictError("sitter_review verdict must be a YAML mapping")
    verdict = payload["sitter_review"]
    result: dict[str, str | None] = {}
    for key in ("architecture", "scope", "numerical_evidence"):
        value = str(verdict.get(key) or "").strip().lower()
        if value not in REVIEW_STATUS:
            raise ReviewVerdictError(f"invalid sitter_review.{key}: {value or '<missing>'}")
        result[key] = value
    overall = max(
        (str(result[key]) for key in ("architecture", "scope", "numerical_evidence")),
        key={"pass": 0, "warn": 1, "block": 2}.get,
    )
    route_value = verdict.get("remediation_route")
    route = None if route_value in {None, "", "null"} else str(route_value).strip()
    if overall == "block":
        if route not in REMEDIATION_ROUTES:
            raise ReviewVerdictError(
                "BLOCK sitter_review requires remediation_route implementation or awaiting-production-design"
            )
    elif route is not None:
        raise ReviewVerdictError("non-BLOCK sitter_review must not set remediation_route")
    result["overall"] = overall
    result["remediation_route"] = route
    return result
