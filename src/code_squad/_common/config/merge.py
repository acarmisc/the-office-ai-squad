"""Schema-aware deep merge and the tighten-only rules for lower layers (brief 4.8).

``merge_layers`` applies an overlay onto a base: dicts merge key by key, lists are
replaced unless the field is marked ``x-mergeable-set`` (then unioned, base order
first). ``check_restricted`` walks an overlay against the metadata and reports every
setting a repository or call layer may not make. The caller rejects the whole layer
if any violation is returned.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from code_squad._common.config.meta import (
    FieldMeta,
    ceiling_breach,
    field_meta,
    lookup,
    shape_of,
)
from code_squad._common.config.schema import (
    APPROVE_ORDER,
    DEFAULT_SECRET_PATTERNS,
    FLOOR_RULES,
    SquadFields,
)
from code_squad._common.tool_policy import TOOL_POLICY, ToolClass

Layer = Literal["repo", "call"]


@dataclass(frozen=True)
class Violation:
    path: str
    reason: str

    def __str__(self) -> str:
        return f"{self.path}: {self.reason}" if self.path else self.reason


def merge_layers(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``base`` with ``overlay`` applied; neither input is mutated."""
    return _merge_node(SquadFields, dict(base), dict(overlay))


def _merge_node(
    model: type[BaseModel], base: dict[str, Any], overlay: dict[str, Any]
) -> dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        field = model.model_fields.get(key)
        if field is None:
            out[key] = value
            continue
        kind, sub = shape_of(field.annotation)
        current = out.get(key)
        if kind == "model" and isinstance(value, dict) and sub is not None:
            base_node = current if isinstance(current, dict) else {}
            out[key] = _merge_node(sub, base_node, value)
        elif kind == "dict_model" and isinstance(value, dict) and sub is not None:
            merged = dict(current) if isinstance(current, dict) else {}
            for item_key, item in value.items():
                prior = merged.get(item_key)
                if isinstance(item, dict):
                    prior_node = prior if isinstance(prior, dict) else {}
                    merged[item_key] = _merge_node(sub, prior_node, item)
                else:
                    merged[item_key] = item
            out[key] = merged
        elif kind == "dict" and isinstance(value, dict):
            prior_map = current if isinstance(current, dict) else {}
            out[key] = {**prior_map, **value}
        elif (
            kind == "list"
            and isinstance(value, list)
            and field_meta(model, key).mergeable_set
        ):
            prior_list = current if isinstance(current, list) else []
            out[key] = _union(prior_list, value)
        else:
            out[key] = value
    return out


def _union(base: list[Any], extra: list[Any]) -> list[Any]:
    result = list(base)
    for item in extra:
        if item not in result:
            result.append(item)
    return result


def check_restricted(
    base_effective: Mapping[str, Any],
    overlay: Mapping[str, Any],
    layer: Layer,
) -> list[Violation]:
    """Report every setting in ``overlay`` that ``layer`` may not change."""
    root = dict(base_effective)
    violations: list[Violation] = []
    _check_node(SquadFields, root, dict(overlay), "", root, layer, violations)
    _check_always_run(root, overlay, layer, violations)
    return violations


def _check_always_run(
    root: Mapping[str, Any],
    overlay: Mapping[str, Any],
    layer: Layer,
    out: list[Violation],
) -> None:
    """Agents in ``routing.always_run`` may not be disabled by a lower layer."""
    routing = root.get("routing")
    always_run = routing.get("always_run") if isinstance(routing, Mapping) else None
    agents = overlay.get("agents")
    if not isinstance(always_run, list) or not isinstance(agents, Mapping):
        return
    for agent_id, entry in agents.items():
        if agent_id not in always_run or not isinstance(entry, Mapping):
            continue
        if _is_disabled(entry.get("enabled")):
            out.append(
                Violation(
                    f"agents.{agent_id}.enabled",
                    f"agent '{agent_id}' is in routing.always_run and cannot be "
                    f"disabled at the {layer} layer",
                )
            )


def _is_disabled(value: Any) -> bool:
    """True for values that the bool field would coerce to False."""
    if isinstance(value, str):
        return value.strip().lower() in {"false", "no", "off", "0"}
    return value is False or (type(value) is int and value == 0)


def _check_node(
    model: type[BaseModel],
    base_node: Any,
    overlay: dict[str, Any],
    prefix: str,
    root: dict[str, Any],
    layer: Layer,
    out: list[Violation],
) -> None:
    base_map: dict[str, Any] = base_node if isinstance(base_node, dict) else {}
    for key, value in overlay.items():
        field = model.model_fields.get(key)
        if field is None:
            continue
        path = f"{prefix}{key}"
        base_value = base_map.get(key)
        meta = field_meta(model, key)
        if meta.merge == "org_only":
            if not _is_noop(value, base_value):
                out.append(
                    Violation(
                        path, f"org-only setting; not allowed in the {layer} layer"
                    )
                )
            continue
        kind, sub = shape_of(field.annotation)
        if kind == "model" and isinstance(value, dict) and sub is not None:
            _check_node(
                sub, _or_defaults(base_value, sub), value, f"{path}.", root, layer, out
            )
            continue
        if kind == "dict_model" and isinstance(value, dict) and sub is not None:
            for item_key, item in value.items():
                if not isinstance(item, dict):
                    continue
                prior = (
                    base_value.get(item_key) if isinstance(base_value, dict) else None
                )
                _check_node(
                    sub,
                    _or_defaults(prior, sub),
                    item,
                    f"{path}.{item_key}.",
                    root,
                    layer,
                    out,
                )
            continue
        _check_leaf(meta, path, base_value, value, root, layer, out)


def _check_leaf(
    meta: FieldMeta,
    path: str,
    base_value: Any,
    value: Any,
    root: dict[str, Any],
    layer: Layer,
    out: list[Violation],
) -> None:
    if meta.secret_ref and value is not None:
        for name in value if isinstance(value, list) else [value]:
            if not _secret_allowed(str(name), root):
                out.append(
                    Violation(
                        path,
                        f"secret name {name!r} is outside secrets.allowed_patterns",
                    )
                )
    if meta.floor:
        out.extend(_floor_violations(path, value, layer))
    if meta.tool_names and isinstance(value, list):
        for name in value:
            if _is_external_write(str(name)):
                out.append(
                    Violation(
                        path,
                        f"external-write tool {name} cannot be allow-listed "
                        f"in the {layer} layer",
                    )
                )
    if meta.merge == "tighten_only":
        _check_tighten(meta, path, base_value, value, layer, out)
    breach = ceiling_breach(meta, value, root)
    if breach is not None:
        out.append(Violation(path, breach))


def _is_external_write(name: str) -> bool:
    return TOOL_POLICY.get(name) is ToolClass.EXTERNAL_WRITE


def _floor_violations(path: str, value: Any, layer: Layer) -> list[Violation]:
    found: list[Violation] = []
    if isinstance(value, list):
        for rule in value:
            if str(rule).strip().upper() in FLOOR_RULES:
                found.append(Violation(path, f"floor rule {rule} cannot be disabled"))
    elif isinstance(value, dict):
        for rule, severity in value.items():
            if str(rule).strip().upper() not in FLOOR_RULES:
                continue
            if str(severity) != "blocker":
                found.append(
                    Violation(
                        path,
                        f"floor rule {rule} cannot be downgraded in the {layer} layer",
                    )
                )
    return found


def _check_tighten(
    meta: FieldMeta,
    path: str,
    base_value: Any,
    value: Any,
    layer: Layer,
    out: list[Violation],
) -> None:
    if meta.tighten == "subset":
        if base_value is None or value is None:
            return
        extra = [item for item in value if item not in base_value]
        if extra:
            out.append(
                Violation(
                    path, f"adds {extra}; the {layer} layer may only narrow this list"
                )
            )
    elif meta.tighten == "le":
        if base_value is None:
            return
        if value is None:
            out.append(Violation(path, f"the {layer} layer may not remove this limit"))
        elif meta.order:
            if _order_index(meta, value) > _order_index(meta, base_value):
                out.append(
                    Violation(path, f"the {layer} layer may not loosen this setting")
                )
        elif value > base_value:
            out.append(
                Violation(
                    path,
                    f"{value} is above the inherited {base_value}; the {layer} layer "
                    "may only lower it",
                )
            )
    elif meta.tighten in ("true", "false"):
        if base_value is None:
            return
        tighter_is_true = meta.tighten == "true"
        if _tightness(value, tighter_is_true) < _tightness(base_value, tighter_is_true):
            out.append(
                Violation(path, f"the {layer} layer may not loosen this setting")
            )


def _order_index(meta: FieldMeta, value: Any) -> int:
    order = meta.order or APPROVE_ORDER
    return order.index(value) if value in order else len(order)


def _tightness(value: Any, tighter_is_true: bool) -> int:
    return 1 if bool(value) == tighter_is_true else 0


def _secret_allowed(name: str, root: Mapping[str, Any]) -> bool:
    configured = lookup(dict(root), "secrets.allowed_patterns")
    patterns = configured if isinstance(configured, list) else DEFAULT_SECRET_PATTERNS
    return any(re.fullmatch(str(pattern), name) for pattern in patterns)


def _is_noop(value: Any, base: Any) -> bool:
    """True when ``value`` restates what the lower layers already resolved."""
    if isinstance(value, dict):
        base_map: dict[str, Any] = base if isinstance(base, dict) else {}
        return all(_is_noop(item, base_map.get(key)) for key, item in value.items())
    return bool(value == base)


def _or_defaults(value: Any, model: type[BaseModel]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return model().model_dump(mode="json")
