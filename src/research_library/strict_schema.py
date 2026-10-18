"""Strict JSON-Schema-subset validator shared by the domain layers.

Issue #15 introduces a second strict domain layer (professional assets,
``research_library.assets``). The validator semantics it needs are exactly the
ones ``research_library.evidence`` already implements for Issue #14, so the
core lives here once and both layers call it:

- ``additionalProperties: false`` (unknown fields are rejected, never ignored),
- numeric ``minimum``/``maximum`` bounds,
- string ``pattern``/``minLength``/``maxLength``, array ``minItems``/``maxItems``,
  ``const``/``enum``, nested objects/arrays, ``type`` (with the bool/int
  subtlety handled: ``true`` is not an integer).

This is intentionally a superset of the governance mini-validator
(``research_library.governance.validate``), which ignores
``additionalProperties`` and numeric bounds and must therefore never be used
as the strict entry for domain records (see docs/evidence/EVIDENCE-MODEL.md
§3.1).

Not JSON-Schema-complete by design: no ``$ref``/``oneOf``/``if-then`` support
(schemas are written flat, cross-field rules live in the domain modules).
"""
from __future__ import annotations

import re

TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def type_ok(value, expected: str) -> bool:
    """One JSON type check, with bool/number subtleties handled strictly."""
    target = TYPE_MAP[expected]
    if expected == "integer" and isinstance(value, bool):
        return False  # bool is an int subclass; only a real integer matches
    if expected == "number" and isinstance(value, bool):
        return False
    return isinstance(value, target)


def strict_validate(data, schema, path: str, errors: list[str]) -> None:
    """Validate ``data`` against a schema subset; append error strings to ``errors``.

    Same behavior as the original Issue #14 implementation in
    ``research_library.evidence`` (moved here verbatim so the assets layer can
    share it); ``errors`` stays empty for valid data.
    """
    if not isinstance(schema, dict):
        errors.append(f"{path}: invalid schema node (not an object)")
        return
    expected_type = schema.get("type")
    if expected_type is not None:
        types = [expected_type] if isinstance(expected_type, str) else list(expected_type)
        if not any(type_ok(data, t) for t in types):
            errors.append(f"{path}: expected type {'/'.join(types)}, got {type(data).__name__}")
            return
    if "const" in schema and data != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}, got {data!r}")
    if "enum" in schema and data not in schema["enum"]:
        errors.append(f"{path}: {data!r} not in enum {schema['enum']!r}")
    if isinstance(data, str):
        if "minLength" in schema and len(data) < schema["minLength"]:
            errors.append(f"{path}: shorter than minLength={schema['minLength']}")
        if "maxLength" in schema and len(data) > schema["maxLength"]:
            errors.append(f"{path}: longer than maxLength={schema['maxLength']}")
        if "pattern" in schema and re.search(schema["pattern"], data) is None:
            errors.append(f"{path}: {data!r} does not match pattern {schema['pattern']!r}")
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if "minimum" in schema and data < schema["minimum"]:
            errors.append(f"{path}: {data} below minimum={schema['minimum']}")
        if "maximum" in schema and data > schema["maximum"]:
            errors.append(f"{path}: {data} above maximum={schema['maximum']}")
    if isinstance(data, list):
        if "minItems" in schema and len(data) < schema["minItems"]:
            errors.append(f"{path}: fewer than minItems={schema['minItems']}")
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            errors.append(f"{path}: more than maxItems={schema['maxItems']}")
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(data):
                strict_validate(item, item_schema, f"{path}[{i}]", errors)
    if isinstance(data, dict):
        for key in schema.get("required", []):
            if key not in data:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in data:
                if key not in properties:
                    errors.append(f"{path}: unexpected field {key!r} (additionalProperties=false)")
        for key, sub in properties.items():
            if key in data:
                strict_validate(data[key], sub, f"{path}.{key}", errors)
