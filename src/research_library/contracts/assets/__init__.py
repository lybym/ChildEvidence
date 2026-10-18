"""Machine-checkable professional-asset contract schemas (Issue #15).

Strict JSON-Schema subset documents consumed by
``research_library.assets`` (validator
``research_library.assets.validate_record``). Packaged as package data so a
relocated/installed package can load and validate records without the
repository checkout.

Envelope: every record carries ``schema_version`` const ``ce.assets/1``.
Every object schema sets ``additionalProperties: false`` — assets are
declarative data only, no executable field can be smuggled in, and unknown
fields are rejected instead of being silently ignored by partial validators.

The ``fixtures/`` subdirectory holds the minimal synthetic demo asset chain
(``demo-*`` ids, ``basis_kind='design_choice'``, drafts, never eligible) —
see ``research_library.assets.seed_demo``.
"""
