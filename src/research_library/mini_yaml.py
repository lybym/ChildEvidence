"""Minimal YAML subset parser.

The research-library configs are written in a deliberately small YAML subset
(nested maps, lists of scalars, lists of maps, scalar values, comments) so the
pipeline runs on the Python standard library only, without PyYAML.

Supported:
  key: value
  key:            (nested block, indented deeper)
  - item          (list of scalars)
  - key: value    (list of maps; deeper-indented keys belong to the same item)
  full-line comments starting with '#'
Not supported: inline '#' comments after values, multi-line strings, anchors,
tabs. Config files in this repo stay inside the subset; unit-tested in
tests/test_mini_yaml.py.
"""

from __future__ import annotations

import re

__all__ = ["parse", "YAMLError"]


class YAMLError(ValueError):
    pass


_KEY_RE = re.compile(r"^[A-Za-z0-9_.\-]+:(\s|$)")


def parse(text: str):
    lines = []
    for raw in text.splitlines():
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise YAMLError("tabs are not allowed for indentation")
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(raw.rstrip())
    if not lines:
        return {}
    value, next_i = _parse_block(lines, 0, _indent_of(lines[0]))
    if next_i != len(lines):
        raise YAMLError(f"unparsed content at line {next_i + 1}: {lines[next_i]!r}")
    return value


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_block(lines, i, indent):
    if lines[i].strip().startswith("- "):
        return _parse_list(lines, i, indent)
    return _parse_map(lines, i, indent)


def _split_kv(stripped: str):
    m = re.match(r"^([A-Za-z0-9_.\-]+):(?:[ ]+(.*))?$", stripped)
    if not m:
        return None, None, None
    return m.group(1), ":", m.group(2)


def _looks_like_kv(stripped: str) -> bool:
    return _KEY_RE.match(stripped) is not None


def _parse_map(lines, i, indent):
    result: dict = {}
    while i < len(lines):
        ind = _indent_of(lines[i])
        if ind < indent:
            break
        if ind > indent:
            raise YAMLError(f"unexpected indent at line {i + 1}: {lines[i]!r}")
        stripped = lines[i].strip()
        if stripped.startswith("- "):
            break
        key, sep, rest = _split_kv(stripped)
        if sep is None:
            raise YAMLError(f"expected 'key: value' at line {i + 1}: {lines[i]!r}")
        if rest is None or rest == "":
            if i + 1 < len(lines) and _indent_of(lines[i + 1]) > indent:
                value, i = _parse_block(lines, i + 1, _indent_of(lines[i + 1]))
                result[key] = value
                continue
            if (
                i + 1 < len(lines)
                and _indent_of(lines[i + 1]) == indent
                and lines[i + 1].strip().startswith("- ")
            ):
                value, i = _parse_list(lines, i + 1, indent)
                result[key] = value
                continue
            result[key] = None
            i += 1
        else:
            result[key] = _scalar(rest)
            i += 1
    return result, i


def _parse_list(lines, i, indent):
    result: list = []
    while i < len(lines):
        ind = _indent_of(lines[i])
        if ind < indent:
            break
        if ind > indent:
            raise YAMLError(f"unexpected indent in list at line {i + 1}: {lines[i]!r}")
        stripped = lines[i].strip()
        if not stripped.startswith("- "):
            break
        item_text = stripped[2:].strip()
        dash_col = ind + 2
        if _looks_like_kv(item_text):
            key, _, rest = _split_kv(item_text)
            item: dict = {}
            if rest:
                item[key] = _scalar(rest)
                i += 1
            else:
                if i + 1 < len(lines) and _indent_of(lines[i + 1]) > dash_col:
                    value, i = _parse_block(lines, i + 1, _indent_of(lines[i + 1]))
                    item[key] = value
                else:
                    item[key] = None
                    i += 1
            while (
                i < len(lines)
                and _indent_of(lines[i]) >= dash_col
                and not lines[i].strip().startswith("- ")
            ):
                sub_value, i = _parse_map(lines, i, _indent_of(lines[i]))
                item.update(sub_value)
            result.append(item)
        else:
            result.append(_scalar(item_text))
            i += 1
    return result, i


def _scalar(s: str):
    s = s.strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        return s[1:-1]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        items = [part.strip() for part in inner.split(",")]
        return [_scalar(part) for part in items if part]
    low = s.lower()
    if low in ("null", "~"):
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s
