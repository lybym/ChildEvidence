"""Machine-checkable evidence-domain contract schemas (Issue #14).

Strict JSON-Schema subset documents consumed by
``research_library.evidence`` (validator ``research_library.evidence.validate_record``).
Packaged as package data so a relocated/installed package can load and
validate records without the repository checkout (Issue #14 验收 #3).

Envelope: every record carries ``schema_version`` const ``ce.evidence/1``.
Every object schema sets ``additionalProperties: false`` — unknown fields are
rejected instead of being silently ignored by partial validators.
"""
