"""Merge-policy metadata carried on schema fields and generic schema walkers.

Every field of the configuration schema declares its policy through
``json_schema_extra`` so the same metadata drives validation, JSON Schema output
and the tighten-only checks. Keys:

- ``x-merge``: ``free`` (default), ``tighten_only`` or ``org_only``.
- ``x-mergeable-set``: list fields are unioned across layers instead of replaced.
- ``x-tighten``: how a lower layer may move the value (``le``, ``subset``,
  ``true``, ``false``); ``x-order`` gives the enum order used by ``le``.
- ``x-ceiling``: dotted path into the effective config holding the platform limit.
- ``x-secret-ref``: the value is a secret name and must match the allowed patterns.
- ``x-floor``: the value is a rule id (or a map keyed by rule id) that floor rules
  restrict.
"""

from __future__ import annotations

import types
from dataclasses import dataclass
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel

MergePolicy = Literal["free", "tighten_only", "org_only"]
Tighten = Literal["le", "subset", "true", "false"]
Shape = Literal["model", "dict_model", "dict", "list", "scalar"]


@dataclass(frozen=True)
class FieldMeta:
    merge: MergePolicy = "free"
    mergeable_set: bool = False
    tighten: Tighten | None = None
    order: tuple[str, ...] = ()
    ceiling: str | None = None
    secret_ref: bool = False
    floor: bool = False
    tool_names: bool = False


def field_meta(model_cls: type[BaseModel], field_name: str) -> FieldMeta:
    info = model_cls.model_fields[field_name]
    extra = info.json_schema_extra
    data: dict[str, Any] = extra if isinstance(extra, dict) else {}
    merge: MergePolicy = data.get("x-merge", "free")
    tighten: Tighten | None = data.get("x-tighten")
    return FieldMeta(
        merge=merge,
        mergeable_set=bool(data.get("x-mergeable-set", False)),
        tighten=tighten,
        order=tuple(str(item) for item in data.get("x-order", ())),
        ceiling=data.get("x-ceiling"),
        secret_ref=bool(data.get("x-secret-ref", False)),
        floor=bool(data.get("x-floor", False)),
        tool_names=bool(data.get("x-tool-names", False)),
    )


def merge_policy(model_cls: type[BaseModel], field_name: str) -> MergePolicy:
    return field_meta(model_cls, field_name).merge


def unwrap_optional(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def shape_of(annotation: Any) -> tuple[Shape, Any]:
    """Classify a field annotation and return the nested model class, if any."""
    annotated = unwrap_optional(annotation)
    if isinstance(annotated, type) and issubclass(annotated, BaseModel):
        return "model", annotated
    origin = get_origin(annotated)
    args = get_args(annotated)
    if origin is dict and len(args) == 2:
        value = unwrap_optional(args[1])
        if isinstance(value, type) and issubclass(value, BaseModel):
            return "dict_model", value
        return "dict", None
    if origin is list:
        return "list", None
    return "scalar", None


def lookup(root: dict[str, Any], dotted: str) -> Any:
    node: Any = root
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def ceiling_breach(meta: FieldMeta, value: Any, root: dict[str, Any]) -> str | None:
    """Return a reason when ``value`` exceeds the platform ceiling for this field."""
    if meta.ceiling is None or value is None:
        return None
    limit = lookup(root, meta.ceiling)
    if not isinstance(limit, int | float) or isinstance(limit, bool):
        return None
    measured: Any = len(value) if isinstance(value, str) else value
    numeric = isinstance(measured, int | float) and not isinstance(measured, bool)
    if numeric and measured > limit:
        return f"{measured} exceeds the platform ceiling {meta.ceiling}={limit}"
    return None


def ceiling_violations(
    model_cls: type[BaseModel],
    node: dict[str, Any],
    root: dict[str, Any],
    prefix: str = "",
) -> list[str]:
    """Walk a dumped config and report every value above its platform ceiling."""
    problems: list[str] = []
    for name, info in model_cls.model_fields.items():
        value = node.get(name)
        if value is None:
            continue
        path = f"{prefix}{name}"
        kind, sub = shape_of(info.annotation)
        if kind == "model" and isinstance(value, dict):
            problems += ceiling_violations(sub, value, root, f"{path}.")
        elif kind == "dict_model" and isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, dict):
                    problems += ceiling_violations(sub, item, root, f"{path}.{key}.")
        else:
            reason = ceiling_breach(field_meta(model_cls, name), value, root)
            if reason is not None:
                problems.append(f"{path}: {reason}")
    return problems
