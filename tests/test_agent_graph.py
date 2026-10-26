"""The agent graph contract is self-consistent: templates and the legacy draft
validate, every template edge joins type-compatible ports of registered
components, and the canonical hash fixture reproduces. The gateway (Go) and
agent-runtime (Python) assert the same fixture and registry bytes."""

import copy
import re
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1] / "agent-graph"
GRAPH = json.loads((ROOT / "v2.schema.json").read_text())
EVENT = json.loads((ROOT / "run-event.v1.schema.json").read_text())
ARTIFACT = json.loads((ROOT / "artifact.v1.schema.json").read_text())
COMPONENTS = json.loads((ROOT / "components.v1.json").read_text())
TEMPLATES = sorted((ROOT / "templates").glob("*.json"))
LEGACY = json.loads((ROOT / "examples/v1-draft.json").read_text())
HASH = json.loads((ROOT / "examples/hash-fixture.json").read_text())
BY_KIND = {component["kind"]: component for component in COMPONENTS["components"]}
CONVERSIONS = {(item["from"], item["to"]) for item in COMPONENTS["conversions"]}


def graph_errors(document):
    return list(jsonschema.Draft202012Validator(GRAPH).iter_errors(document))


def canonical(graph):
    nodes = sorted(
        ({"id": n["id"], "kind": n["kind"],
          "config": {k: v for k, v in (n.get("config") or {}).items() if v != ""}}
         for n in graph["nodes"]),
        key=lambda n: n["id"],
    )
    edges = []
    for edge in graph["edges"]:
        item = {"from": edge["from"], "to": edge["to"]}
        for key in ("from_port", "to_port"):
            if edge.get(key):
                item[key] = edge[key]
        edges.append(item)
    edges.sort(key=lambda e: (e["from"], e.get("from_port", ""), e["to"], e.get("to_port", "")))
    document = {"schema_version": 2, "nodes": nodes, "edges": edges, "settings": graph.get("settings") or {}}
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def compatible(output_type, accepts):
    return output_type in accepts or any((output_type, target) in CONVERSIONS for target in accepts)


def test_registry_is_self_consistent():
    assert len(BY_KIND) == len(COMPONENTS["components"]), "duplicate component kind"
    types = set(COMPONENTS["port_types"])
    for source, target in CONVERSIONS:
        assert source in types and target in types
    for component in COMPONENTS["components"]:
        assert set(component) >= {"kind", "version", "category", "label", "description", "inputs",
                                  "outputs", "config", "side_effects", "timeout_seconds", "retries"}
        for port in component["outputs"]:
            assert port["type"] in types
        for port in component["inputs"]:
            assert set(port["accepts"]) <= types
        keys = [field["key"] for field in component["config"]]
        assert len(keys) == len(set(keys))
        for field in component["config"]:
            assert field["type"] in {"string", "template", "integer", "enum", "resource", "expression"}
            if field["type"] == "resource":
                assert field["resource"] in {"model", "tool", "knowledge_base", "dataset", "connection"}
            if field["type"] == "integer" and "default" in field:
                assert field["minimum"] <= int(field["default"]) <= field["maximum"]
            if field["type"] == "enum":
                assert field.get("default", field["options"][0]) in field["options"]
            if "pattern" in field:
                re.compile(field["pattern"])
    assert BY_KIND["input"]["singleton"] and BY_KIND["output"]["singleton"]
    assert BY_KIND["tool"]["side_effects"] and BY_KIND["api"]["side_effects"]


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.stem)
def test_templates_are_valid_typed_dags(path):
    template = json.loads(path.read_text())
    assert template["id"] == path.stem
    graph = template["graph"]
    assert graph_errors(graph) == []
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert [n["kind"] for n in graph["nodes"]].count("input") == 1
    assert [n["kind"] for n in graph["nodes"]].count("output") == 1
    for node in graph["nodes"]:
        component = BY_KIND[node["kind"]]
        allowed = {field["key"] for field in component["config"]}
        assert set(node.get("config", {})) <= allowed, node["id"]
    indegree = {node_id: 0 for node_id in nodes}
    children = {node_id: [] for node_id in nodes}
    for edge in graph["edges"]:
        source, target = BY_KIND[nodes[edge["from"]]["kind"]], BY_KIND[nodes[edge["to"]]["kind"]]
        out = next(p for p in source["outputs"] if p["name"] == edge["from_port"])
        port = next(p for p in target["inputs"] if p["name"] == edge["to_port"])
        assert compatible(out["type"], port["accepts"]), edge
        indegree[edge["to"]] += 1
        children[edge["from"]].append(edge["to"])
    queue = [node_id for node_id, count in indegree.items() if count == 0]
    visited = 0
    while queue:
        node_id = queue.pop()
        visited += 1
        for child in children[node_id]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    assert visited == len(nodes), "template contains a cycle"


def test_version_one_drafts_remain_valid():
    assert "schema_version" not in LEGACY
    assert graph_errors(LEGACY) == []


@pytest.mark.parametrize("mutate, fragment", [
    (lambda d: d["nodes"][0].update(id="Bad_Id"), "Bad_Id"),
    (lambda d: d["nodes"][0].update(config={"k": 1}), "1"),
    (lambda d: d["edges"][0].update(via="x"), "via"),
    (lambda d: d.update(settings={"max_steps": 500}), "500"),
    (lambda d: d.update(settings={"max_steps": 1.5}), "1.5"),
    (lambda d: d.update(schema_version=3), "3"),
    (lambda d: d.update(nodes=d["nodes"][:1]), "short"),
])
def test_structural_mistakes_are_rejected(mutate, fragment):
    document = copy.deepcopy(LEGACY)
    mutate(document)
    found = graph_errors(document)
    assert found, "invalid graph accepted"


def test_canonical_hash_fixture_reproduces():
    text = canonical(HASH["graph"])
    assert text == HASH["canonical"]
    assert hashlib.sha256(text.encode()).hexdigest() == HASH["expected_sha256"]
    moved = copy.deepcopy(HASH["graph"])
    moved["nodes"][0]["x"] = 9999
    moved["nodes"][0]["name"] = "Renamed"
    moved["name"] = "Other"
    assert canonical(moved) == text, "layout and labels must not change the behavior hash"
    changed = copy.deepcopy(HASH["graph"])
    changed["nodes"][0]["config"]["template"] = "different"
    assert canonical(changed) != text


def test_artifact_and_event_examples_validate():
    registry = Registry().with_resource("v2.schema.json", Resource.from_contents(GRAPH))
    artifact = {
        "artifact_version": 1, "id": "agv-" + "a" * 24, "design_id": "agd-" + "b" * 24,
        "project_id": "prj-demo", "version": 1, "content_sha256": HASH["expected_sha256"],
        "registry_version": COMPONENTS["registry_version"], "graph": HASH["graph"],
        "source_revision": 3, "author": "ada", "created_at": "2026-10-26T12:00:00Z",
        "runtime": {"graph_module": "agents.native_graph:build_native"},
        "evaluation": {"id": "age-" + "c" * 24, "pass_rate": 1.0, "cases": 4, "gate": 0.8, "passed": True},
    }
    validator = jsonschema.Draft202012Validator(ARTIFACT, registry=registry)
    assert list(validator.iter_errors(artifact)) == []
    broken = copy.deepcopy(artifact)
    broken["runtime"]["graph_module"] = "evil:build"
    assert list(validator.iter_errors(broken))
    event = {"seq": 2, "type": "node.completed", "run_id": "agr-" + "d" * 24, "ts": "2026-10-26T12:00:01Z",
             "node_id": "model", "kind": "model", "duration_ms": 12, "output_preview": "hi",
             "usage": {"input_tokens": 3, "output_tokens": 1, "cost_usd": 0}}
    assert list(jsonschema.Draft202012Validator(EVENT).iter_errors(event)) == []
    event["type"] = "node.exploded"
    assert list(jsonschema.Draft202012Validator(EVENT).iter_errors(event))


def test_failure_prone_components_expose_an_error_port():
    for kind in ("model", "tool", "api", "knowledge", "storage"):
        outputs = [port["name"] for port in BY_KIND[kind]["outputs"]]
        assert outputs[0] == "out" and "error" in outputs, kind
    for kind in ("input", "prompt", "condition", "memory", "extract"):
        assert "error" not in [port["name"] for port in BY_KIND[kind]["outputs"]], kind
    path = re.compile(next(f for f in BY_KIND["extract"]["config"] if f["key"] == "path")["pattern"])
    assert path.match("result.items.0.name") and not path.match("a..b") and not path.match("__import__('os')")
