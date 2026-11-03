"""Published contracts never take a breaking change (docs/compatibility.md).

Every *.schema.json is compared with its version at the latest release tag. A
change that would make a previously valid document invalid fails here: a removed
property or file, a new required field, additionalProperties tightened to false,
a narrowed enum or type, a tighter bound or a changed pattern. A breaking change
belongs in a new versioned file. Each schema must also declare its class."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = sorted(path.relative_to(ROOT).as_posix() for path in ROOT.glob("*/*.schema.json"))
OPEN = {"ingest/step-report.v1.schema.json", "ingest/log-batch.v1.schema.json", "ingest/trace.v1.schema.json"}
# Published before this policy with an open root; tightening it would be breaking.
# Its nodes, edges and settings are closed (docs/compatibility.md).
OPEN_ROOT_CLOSED_PARTS = {"agent-graph/v2.schema.json": ("node", "edge", "settings")}
# Bounds whose increase (upper) or decrease (lower) is a loosening.
UPPER = ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties")
LOWER = ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties")
CHILD_MAPS = ("properties", "$defs", "definitions", "patternProperties", "dependentSchemas")
CHILD_SCHEMAS = ("items", "additionalProperties", "contains", "propertyNames", "if", "then", "else", "not")
CHILD_LISTS = ("allOf", "anyOf", "oneOf", "prefixItems")


def types(node):
    value = node.get("type")
    return {value} if isinstance(value, str) else set(value or [])


def closed(node):
    return node.get("additionalProperties") is False


def breaking_changes(old, new, path="#"):
    """Every way `new` rejects a document that `old` accepted, as readable strings."""
    if not isinstance(old, dict) or not isinstance(new, dict):
        return [] if old == new or new is True else [f"{path}: schema replaced"]
    found = []
    if closed(new) and not closed(old):
        found.append(f"{path}: additionalProperties tightened to false")
    for name in sorted(set(new.get("required", [])) - set(old.get("required", []))):
        found.append(f"{path}: {name!r} became required")
    for name in sorted(set(old.get("properties", {})) - set(new.get("properties", {}))):
        if closed(new) or "properties" in new:
            found.append(f"{path}/properties: {name!r} removed")
    if "enum" in new:
        removed = [value for value in old.get("enum", []) if value not in new["enum"]]
        if removed or "enum" not in old:
            found.append(f"{path}: enum narrowed (removed {removed})" if removed else f"{path}: enum added")
    if "const" in new and old.get("const") != new["const"]:
        found.append(f"{path}: const changed")
    if types(new) and (not types(old) or not types(old) <= types(new)):
        if not (types(old) == {"integer"} and "number" in types(new)):
            found.append(f"{path}: type narrowed from {sorted(types(old))} to {sorted(types(new))}")
    for key in UPPER:
        if key in new and (key not in old or new[key] < old[key]):
            found.append(f"{path}: {key} tightened to {new[key]}")
    for key in LOWER:
        if key in new and (key not in old or new[key] > old[key]):
            found.append(f"{path}: {key} tightened to {new[key]}")
    if "pattern" in new and old.get("pattern") != new["pattern"]:
        found.append(f"{path}: pattern changed")
    if "format" in new and old.get("format") != new["format"]:
        found.append(f"{path}: format changed")
    for key in CHILD_MAPS:
        for name in sorted(set(old.get(key, {})) & set(new.get(key, {}))):
            found += breaking_changes(old[key][name], new[key][name], f"{path}/{key}/{name}")
    for key in CHILD_SCHEMAS:
        if key in new and key in old:
            found += breaking_changes(old[key], new[key], f"{path}/{key}")
    for key in CHILD_LISTS:
        for index, (before, after) in enumerate(zip(old.get(key, []), new.get(key, []))):
            found += breaking_changes(before, after, f"{path}/{key}/{index}")
        if key in ("allOf",) and len(new.get(key, [])) > len(old.get(key, [])):
            found.append(f"{path}/{key}: new constraint added")
        if key in ("anyOf", "oneOf") and len(new.get(key, [])) < len(old.get(key, [])):
            found.append(f"{path}/{key}: alternative removed")
    return found


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def release_tag():
    result = git("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*")
    if result.returncode != 0:
        if os.environ.get("CI"):
            pytest.fail("no release tag in this checkout; CI must fetch tags (fetch-depth: 0)")
        pytest.skip("no release tag in this checkout")
    return result.stdout.strip()


def published(tag):
    listing = git("ls-tree", "-r", "--name-only", tag).stdout.split()
    return {name: json.loads(git("show", f"{tag}:{name}").stdout) for name in listing if name.endswith(".schema.json")}


# ---- the checker itself -----------------------------------------------------------

BASE = {"type": "object", "required": ["a"], "additionalProperties": True,
        "properties": {"a": {"type": "string", "maxLength": 10}, "b": {"enum": ["x", "y"]}}}


def changed(**edits):
    new = json.loads(json.dumps(BASE))
    for key, value in edits.items():
        target = new
        *parents, leaf = key.split("__")
        for parent in parents:
            target = target[parent]
        if value is None:
            del target[leaf]
        else:
            target[leaf] = value
    return new


@pytest.mark.parametrize("edits,message", [
    ({"additionalProperties": False}, "additionalProperties tightened"),
    ({"required": ["a", "b"]}, "'b' became required"),
    ({"properties__b": None}, "'b' removed"),
    ({"properties__b__enum": ["x"]}, "enum narrowed"),
    ({"properties__a__type": "integer"}, "type narrowed"),
    ({"properties__a__maxLength": 5}, "maxLength tightened"),
    ({"properties__a__pattern": "^a"}, "pattern changed"),
])
def test_checker_flags_breaking_changes(edits, message):
    assert any(message in item for item in breaking_changes(BASE, changed(**edits)))


@pytest.mark.parametrize("edits", [
    {"properties__c": {"type": "string"}},
    {"properties__b__enum": ["x", "y", "z"]},
    {"properties__a__type": ["string", "null"]},
    {"properties__a__maxLength": 20},
    {"required": []},
    {"description": "annotations are free"},
])
def test_checker_allows_compatible_changes(edits):
    assert breaking_changes(BASE, changed(**edits)) == []


def test_checker_allows_loosening_a_closed_contract():
    old = {**BASE, "additionalProperties": False}
    assert breaking_changes(old, BASE) == []


# ---- the repository ---------------------------------------------------------------

@pytest.mark.parametrize("name", SCHEMAS)
def test_schema_declares_its_class(name):
    document = json.loads((ROOT / name).read_text())
    if name in OPEN_ROOT_CLOSED_PARTS:
        assert document.get("additionalProperties") is True
        for part in OPEN_ROOT_CLOSED_PARTS[name]:
            assert document["$defs"][part]["additionalProperties"] is False, f"{name} $defs/{part} must stay closed"
        return
    expected = name in OPEN
    assert document.get("additionalProperties") is expected, (
        f"{name}: root additionalProperties must be {expected} (docs/compatibility.md)")
    if expected:
        assert document.get("x-kionga-policy") == "open"


def test_published_schemas_have_no_breaking_change():
    tag = release_tag()
    before = published(tag)
    problems = [f"{name}: deleted since {tag}" for name in before if not (ROOT / name).exists()]
    for name, old in before.items():
        if (ROOT / name).exists():
            problems += [f"{name} {item}" for item in breaking_changes(old, json.loads((ROOT / name).read_text()))]
    assert not problems, "breaking changes; add a new versioned schema instead:\n" + "\n".join(problems)


def test_open_contracts_stay_open_once_published():
    # Tightening an open ingest contract is the failure this policy prevents.
    tag = release_tag()
    for name in OPEN & set(published(tag)):
        assert json.loads((ROOT / name).read_text())["additionalProperties"] is True, name
