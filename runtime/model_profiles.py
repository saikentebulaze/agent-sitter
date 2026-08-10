"""Provider-neutral role grades and user-overridable native model selectors."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import yaml

from project_context import ProjectContext


MODEL_GRADES = ("low", "medium", "high")
LEGACY_MODEL_GRADES = {"luna": "low", "terra": "medium", "sol": "high"}
LOCAL_MODEL_CONFIG = Path(".harness/sitter.models.local.yaml")
_ALLOWED_TOP_LEVEL = {"schema_version", "roles", "providers", "allow_grade_aliasing"}
_ALLOWED_ROLE_FIELDS = {"model_grade", "reasoning_effort"}
_ALLOWED_PROVIDER_FIELDS = {"models"}
_ALLOWED_MODEL_FIELDS = {
    "selector",
    "resolution_mode",
    "expected_resolved_model",
    "proxy_provider",
}
_RESOLUTION_MODES = {"native", "explicit-proxy"}


class ModelProfileError(ValueError):
    pass


@dataclass(frozen=True)
class ModelSelection:
    provider: str
    role_id: str
    model_grade: str
    model_selector: str
    reasoning_effort: str
    config_sha256: str
    resolution_mode: str = "native"
    expected_resolved_model: str = ""
    proxy_provider: str = ""


def _mapping(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise ModelProfileError(f"{label} must be a mapping")
    return value


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        raise ModelProfileError(f"missing model profile configuration: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ModelProfileError(f"invalid model profile configuration: {path}") from error
    return _mapping(value, str(path))


def _deep_merge(base: dict, overlay: dict) -> dict:
    result = deepcopy(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _validate_keys(mapping: dict, allowed: set[str], label: str) -> None:
    unknown = sorted(set(map(str, mapping)) - allowed)
    if unknown:
        raise ModelProfileError(f"unknown {label} field: {unknown[0]}")


def _canonical_hash(config: dict) -> str:
    payload = json.dumps(
        config,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_effective_model_profiles(context: ProjectContext) -> tuple[dict, str]:
    default_path = context.adapter_root / "model-profiles.yaml"
    config = _load_yaml(default_path)
    local_path = context.project_root / LOCAL_MODEL_CONFIG
    if local_path.is_file():
        overlay = _load_yaml(local_path)
        _validate_keys(overlay, _ALLOWED_TOP_LEVEL, "top-level")
        config = _deep_merge(config, overlay)
    _validate(config)
    return config, _canonical_hash(config)


def _non_empty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelProfileError(f"{label} must be a non-empty string")
    result = value.strip()
    if any(ord(character) < 32 for character in result):
        raise ModelProfileError(f"{label} contains control characters")
    return result


def _validate(config: dict) -> None:
    _validate_keys(config, _ALLOWED_TOP_LEVEL, "top-level")
    if config.get("schema_version") != 1:
        raise ModelProfileError("model profile schema_version must be 1")

    roles = _mapping(config.get("roles"), "roles")
    providers = _mapping(config.get("providers"), "providers")
    if not roles:
        raise ModelProfileError("model profile roles cannot be empty")
    if not providers:
        raise ModelProfileError("model profile providers cannot be empty")

    for role_id, raw_role in roles.items():
        role = _mapping(raw_role, f"roles.{role_id}")
        _validate_keys(role, _ALLOWED_ROLE_FIELDS, f"roles.{role_id}")
        grade = str(role.get("model_grade") or "")
        if grade not in MODEL_GRADES:
            raise ModelProfileError(f"roles.{role_id}.model_grade is invalid: {grade}")
        _non_empty_text(role.get("reasoning_effort"), f"roles.{role_id}.reasoning_effort")

    allow_aliasing = bool(config.get("allow_grade_aliasing", False))
    for provider_id, raw_provider in providers.items():
        provider = _mapping(raw_provider, f"providers.{provider_id}")
        _validate_keys(provider, _ALLOWED_PROVIDER_FIELDS, f"providers.{provider_id}")
        models = _mapping(provider.get("models"), f"providers.{provider_id}.models")
        selectors: list[str] = []
        for grade in MODEL_GRADES:
            label = f"providers.{provider_id}.models.{grade}"
            model = _mapping(models.get(grade), label)
            _validate_keys(model, _ALLOWED_MODEL_FIELDS, label)
            selector = _non_empty_text(model.get("selector"), f"{label}.selector")
            if provider_id == "claude" and selector == "inherit":
                raise ModelProfileError("Claude governed child roles must not use model: inherit")
            mode = str(model.get("resolution_mode") or "native").strip()
            if mode not in _RESOLUTION_MODES:
                raise ModelProfileError(f"{label}.resolution_mode is invalid: {mode}")
            expected = str(model.get("expected_resolved_model") or "").strip()
            proxy = str(model.get("proxy_provider") or "").strip()
            if mode == "explicit-proxy":
                _non_empty_text(expected, f"{label}.expected_resolved_model")
                _non_empty_text(proxy, f"{label}.proxy_provider")
                if provider_id != "claude":
                    raise ModelProfileError(
                        f"{label}.resolution_mode explicit-proxy is only supported by Claude"
                    )
            elif expected or proxy:
                raise ModelProfileError(
                    f"{label} may set expected_resolved_model/proxy_provider only with explicit-proxy"
                )
            selectors.append(selector)
        if not allow_aliasing and len(set(selectors)) != len(selectors):
            raise ModelProfileError(
                f"providers.{provider_id} maps multiple model grades to the same selector"
            )


def normalize_model_grade(value: str) -> str:
    normalized = LEGACY_MODEL_GRADES.get(value, value)
    if normalized not in MODEL_GRADES:
        raise ModelProfileError(f"invalid model grade: {value}")
    return normalized


def resolve_model_selection(
    context: ProjectContext,
    provider_id: str,
    role_id: str,
) -> ModelSelection:
    config, digest = load_effective_model_profiles(context)
    roles = config["roles"]
    providers = config["providers"]
    if role_id not in roles:
        raise ModelProfileError(f"unknown Claude role: {role_id}")
    if provider_id not in providers:
        raise ModelProfileError(f"model profile has no provider: {provider_id}")

    role = roles[role_id]
    grade = normalize_model_grade(str(role["model_grade"]))
    model = providers[provider_id]["models"][grade]
    return ModelSelection(
        provider=provider_id,
        role_id=role_id,
        model_grade=grade,
        model_selector=str(model["selector"]).strip(),
        reasoning_effort=str(role["reasoning_effort"]),
        config_sha256=digest,
        resolution_mode=str(model.get("resolution_mode") or "native").strip(),
        expected_resolved_model=str(model.get("expected_resolved_model") or "").strip(),
        proxy_provider=str(model.get("proxy_provider") or "").strip(),
    )
