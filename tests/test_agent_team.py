"""The agent team contract is self-consistent: valid examples validate, each invalid
example fails for its stated reason and no other, templates can be instantiated, and
the security rules a schema can carry are present. The README's normative rules are
pinned too, because the gateway, the runner and the sandbox manager implement them."""

import copy
import json
import re
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1] / "agent-team"
SCHEMAS = {path.name.split(".")[0]: json.loads(path.read_text()) for path in ROOT.glob("*.schema.json")}
REGISTRY = Registry().with_resources(
    (schema["$id"], Resource.from_contents(schema)) for schema in SCHEMAS.values())
VALID = sorted((ROOT / "examples/valid").glob("*.json"))
INVALID = sorted((ROOT / "examples/invalid").glob("*.json"))
TEMPLATES = {path.stem: json.loads(path.read_text()) for path in (ROOT / "templates").glob("*.json")}
README = (ROOT / "README.md").read_text()
SANDBOX = SCHEMAS["sandbox-api"]
HEX = "a" * 24
RUN = "atr-" + HEX


def validator(target):
    if target.startswith("sandbox."):
        schema = {"$ref": SANDBOX["$id"] + "#/$defs/" + target.split(".", 1)[1]}
    else:
        schema = SCHEMAS[target]
    return jsonschema.Draft202012Validator(schema, registry=REGISTRY)


def errors(target, document):
    return list(validator(target).iter_errors(document))


def example(name):
    return json.loads((ROOT / "examples/valid" / f"{name}.json").read_text())


def walk(node, path="#"):
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from walk(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, f"{path}/{index}")


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_schema_is_well_formed_closed_and_portable(name):
    schema = SCHEMAS[name]
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    for path, node in walk(schema):
        if not path.endswith(("/x-environment", "/x-labels")) and isinstance(node.get("properties"), dict) \
                and node.get("type") == "object":
            assert node.get("additionalProperties") is False, f"{name} {path} is open"
        pattern = node.get("pattern")
        if isinstance(pattern, str):
            re.compile(pattern)
            assert "(?" not in pattern, f"{name} {path}: lookaround and groups with flags are not portable to Go"


def test_examples_cover_every_contract():
    targets = {path.stem.split("--")[0] for path in VALID}
    assert {"agent-definition", "team", "team-run-event", "runner-turn-request", "runner-turn-response",
            "runner-embedding-request", "runner-embedding-response"} <= targets
    operations = {op[key].rsplit("/", 1)[1] for op in SANDBOX["x-operations"]
                  for key in ("request", "response", "query") if key in op}
    assert {f"sandbox.{name}" for name in operations} <= targets
    assert {path.stem.split("--")[0] for path in INVALID} <= targets


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.stem)
def test_valid_examples_validate(path):
    assert errors(path.stem.split("--")[0], json.loads(path.read_text())) == []


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.stem)
def test_invalid_examples_fail_for_the_stated_reason(path):
    case = json.loads(path.read_text())
    assert set(case) == {"target", "why", "path", "message", "document"}
    assert path.stem.startswith(case["target"] + "--")
    found = errors(case["target"], case["document"])
    assert found, "invalid document accepted"
    assert {error.json_path for error in found} == {case["path"]}, [e.message for e in found]
    assert any(case["message"] in error.message for error in found), [e.message for e in found]


@pytest.mark.parametrize("target, field, low, high", [
    ("agent-definition--sandbox", "max_turns", 1, 500),
    ("agent-definition--sandbox", "max_tokens", 1, 5_000_000),
    ("agent-definition--sandbox", "max_seconds", 60, 14_400),
    ("team--stored", "max_workers_total", 1, 50),
    ("team--stored", "max_concurrent_workers", 1, 16),
    ("team--stored", "max_tokens", 1, 20_000_000),
    ("team--stored", "max_seconds", 60, 86_400),
])
def test_limit_bounds_are_exact(target, field, low, high):
    schema_target = target.split("--")[0]
    document = example(target)
    for value, ok in ((low, True), (high, True), (low - 1, False), (high + 1, False)):
        document["limits"][field] = value
        assert (errors(schema_target, document) == []) is ok, (field, value)


def test_definition_workspace_rule_applies_to_both_grants():
    for grant in ({"kind": "sandbox"}, {"kind": "git", "repository": "https://github.com/o/r"}):
        document = {"name": "a", "description": "d", "instructions": "i", "tools": [grant]}
        assert errors("agent-definition", document), grant
        document["workspace"] = "none"
        assert errors("agent-definition", document), grant
        document["workspace"] = "sandbox"
        assert errors("agent-definition", document) == [], grant
    resource = {"name": "a", "description": "d", "instructions": "i", "tools": [{"kind": "tool", "ref": "lookup"}]}
    assert errors("agent-definition", resource) == [], "non-sandbox teams need no workspace"


def test_id_prefixes_do_not_collide_with_existing_resources():
    assert SCHEMAS["agent-definition"]["properties"]["id"]["pattern"].startswith("^adf-")
    assert SCHEMAS["team"]["properties"]["id"]["pattern"].startswith("^atm-")
    assert SCHEMAS["team"]["properties"]["members"]["items"]["pattern"].startswith("^adf-")
    text = "".join(path.read_text() for path in VALID)
    assert not re.search(r"\b(agd|agt|apc)-", text), "valid examples must use the current prefixes"


def test_event_types_match_the_contract_and_worker_events_name_the_worker():
    assert set(SCHEMAS["team-run-event"]["properties"]["type"]["enum"]) == {
        "run.started", "run.resumed", "run.finished", "worker.spawned", "worker.turn", "worker.tool_call",
        "worker.tool_result", "worker.retrying", "worker.waiting_approval", "worker.message", "worker.finished"}
    base = {"seq": 1, "run_id": RUN, "ts": "2026-11-04T12:00:00Z"}
    for event_type in SCHEMAS["team-run-event"]["properties"]["type"]["enum"]:
        if event_type.startswith("worker.") and event_type != "worker.message":
            messages = [e.message for e in errors("team-run-event", {**base, "type": event_type})]
            assert "'worker_id' is a required property" in messages, event_type


def test_person_message_cannot_claim_a_worker_sender_format():
    event = example("team-run-event--person-message")
    event["from"] = "Person"
    assert errors("team-run-event", event)
    event["from"] = "atw-" + HEX
    assert errors("team-run-event", event) == []


def test_runner_request_messages_are_framed_by_the_gateway():
    frame = re.compile(r'^<kionga-data source="[^"]+" kind="[a-z-]+" nonce="([^"]+)">.*</kionga-data>$', re.S)
    framed = [m for m in example("runner-turn-request--tool-round")["messages"] if m["role"] in ("user", "tool")]
    nonces = [frame.match(message["content"]).group(1) for message in framed]
    assert len(framed) == 2 and len(set(nonces)) == 2, "each delivery has a fresh nonce"


def test_runner_error_codes_are_the_four_the_gateway_handles():
    codes = SCHEMAS["runner-turn-response"]["$defs"]["error"]["properties"]["code"]["enum"]
    assert set(codes) == {"rate_limited", "provider_unavailable", "invalid_request", "model_error"}


@pytest.mark.parametrize("dimensions,ok", [(1, True), (4096, True), (0, False), (4097, False), (1.5, False), ("8", False)])
def test_embedding_dimensions_match_the_knowledge_base_limits(dimensions, ok):
    assert (errors("runner-embedding-request", {"text": "query", "dimensions": dimensions}) == []) is ok, dimensions


def test_sandbox_operations_are_exactly_the_contract():
    assert {(op["method"], op["path"]) for op in SANDBOX["x-operations"]} == {
        ("POST", "/sandboxes"), ("POST", "/sandboxes/{id}/exec"), ("GET", "/sandboxes/{id}/files"),
        ("PUT", "/sandboxes/{id}/files"), ("POST", "/sandboxes/{id}/git/clone"),
        ("POST", "/sandboxes/{id}/git/push"), ("GET", "/sandboxes/{id}/git/diff"),
        ("DELETE", "/sandboxes/{id}"), ("GET", "/healthz")}
    for op in SANDBOX["x-operations"]:
        for key in ("request", "response", "query"):
            if key in op:
                assert op[key].rsplit("/", 1)[1] in SANDBOX["$defs"], op


def test_sandbox_create_body_has_no_way_to_weaken_isolation():
    allowed = set(SANDBOX["$defs"]["create_request"]["properties"])
    assert allowed == {"run_id", "worker_id", "project_id", "image"}
    assert set(SANDBOX["$defs"]["exec_request"]["properties"]) == {"command", "cwd", "timeout_seconds"}


@pytest.mark.parametrize("branch, ok", [
    (f"kionga/{RUN}/fix-parser", True),
    (f"kionga/{RUN}/v1.2_x", True),
    ("main", False),
    ("master", False),
    (f"refs/heads/kionga/{RUN}/x", False),
    (f"kionga/{RUN}/", False),
    (f"kionga/{RUN}/a/b", False),
    (f"kionga/{RUN}/a..b", False),
    (f"kionga/{RUN}/-x", False),
    (f":kionga/{RUN}/x", False),
    (f"kionga/{RUN}/x\nmain", False),
    (f"kionga/{RUN}/x:main", False),
])
def test_push_branch_rule(branch, ok):
    document = example("sandbox.git_push_request--basic")
    document["branch"] = branch
    assert (errors("sandbox.git_push_request", document) == []) is ok, branch


@pytest.mark.parametrize("path, ok", [
    (".", True), ("a/b.txt", True), (".github/ci.yml", True), ("..hidden", True), ("/workspace", True),
    ("/workspace/", True), ("/workspace/a", True),
    ("..", False), ("../a", False), ("a/../../b", False), ("a/..", False), ("/workspace/..", False),
    ("/workspace/a/../../etc", False), ("/etc/passwd", False), ("/workspaces/a", False), ("", False), ("a\x00b", False),
])
def test_paths_stay_under_workspace(path, ok):
    assert (errors("sandbox.files_query", {"path": path}) == []) is ok, repr(path)


def test_credentials_are_write_only_and_absent_from_responses():
    for name in ("git_clone_request", "git_push_request"):
        assert SANDBOX["$defs"][name]["properties"]["credential"]["writeOnly"] is True
    assert "credential" not in SANDBOX["$defs"]["git_clone_request"]["required"], "public clones need none"
    assert "credential" in SANDBOX["$defs"]["git_push_request"]["required"]
    for name, definition in SANDBOX["$defs"].items():
        if not name.endswith("_request"):
            assert "credential" not in json.dumps(definition.get("properties", {})), name


def test_sandbox_environment_and_helper_label_names():
    assert set(SANDBOX["x-environment"]) == {
        "KIONGA_SANDBOX_URL", "KIONGA_SANDBOX_TOKEN", "KIONGA_SANDBOX_DRIVER", "KIONGA_SANDBOX_NAMESPACE",
        "KIONGA_SANDBOX_STORAGE_CLASS", "KIONGA_SANDBOX_RUNTIME", "KIONGA_SANDBOX_ALLOW_UNSAFE_RUNTIME",
        "KIONGA_SANDBOX_IMAGES", "KIONGA_SANDBOX_GIT_HOSTS", "KIONGA_SANDBOX_TTL_SECONDS"}
    assert "git-helper" in SANDBOX["x-labels"]["kionga.dev/sandbox-role"]
    assert "kionga.dev/sandbox-role=git-helper" in README
    for name in SANDBOX["x-environment"]:
        assert name in README, name


# ---- templates ---------------------------------------------------------------------

COORDINATOR_ONLY = {"spawn_worker", "list_workers", "read_worker_file", "worker_diff"}
SANDBOX_TOOLS = {"exec", "read_file", "write_file", "edit_file", "list_files", "search_files",
                 "git_clone", "git_diff", "git_push"}


def mentions(text, names):
    return {name for name in names if re.search(rf"\b{name}\b", text)}


def test_template_push_instruction_uses_the_short_name():
    bug_fixer = next(a for a in TEMPLATES["code-change"]["agents"] if a["name"] == "bug-fixer")
    assert "short descriptive name" in bug_fixer["instructions"]
    assert "with no / or .. in it" in bug_fixer["instructions"]


def test_required_templates_exist():
    assert set(TEMPLATES) == {"code-change", "research"}
    assert TEMPLATES["code-change"]["team"]["members"] == ["bug-fixer", "reviewer"]
    assert TEMPLATES["research"]["team"]["members"] == ["researcher", "writer"]


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_template_validates_and_instantiates(name):
    template = TEMPLATES[name]
    assert template["id"] == name == template["team"]["name"]
    assert errors("template", template) == []
    agents = {agent["name"]: agent for agent in template["agents"]}
    assert list(agents) == template["team"]["members"]
    for agent in agents.values():
        assert "id" not in agent, "a template agent gets its ID when it is created"
        assert errors("agent-definition", agent) == []
    team = copy.deepcopy(template["team"])
    team["members"] = ["adf-" + format(index, "024x") for index in range(len(team["members"]))]
    assert errors("team", team) == []


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_template_budgets_are_consistent(name):
    template = TEMPLATES[name]
    limits = template["team"]["limits"]
    assert limits["max_concurrent_workers"] <= limits["max_workers_total"]
    for agent in template["agents"]:
        assert agent["limits"]["max_tokens"] <= limits["max_tokens"], agent["name"]
        assert agent["limits"]["max_seconds"] <= limits["max_seconds"], agent["name"]


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_template_instructions_only_use_tools_the_role_has(name):
    template = TEMPLATES[name]
    coordinator = template["team"]["coordinator"]["instructions"]
    assert len(coordinator) > 500 and len(template["team"]["brief"]) > 200
    assert not mentions(coordinator, SANDBOX_TOOLS), "the coordinator has no resource tools"
    assert "spawn_worker" in coordinator and "finish" in coordinator
    for agent in template["agents"]:
        assert agent["name"] in coordinator, "the coordinator must know how to use each member"
        assert len(agent["instructions"]) > 300, agent["name"]
        assert not mentions(agent["instructions"], COORDINATOR_ONLY), f"{agent['name']}: depth is 1"
        if agent["workspace"] == "none":
            assert not mentions(agent["instructions"], SANDBOX_TOOLS), agent["name"]
        assert "finish" in agent["instructions"], agent["name"]


def test_code_change_verifies_rather_than_trusts():
    template = TEMPLATES["code-change"]
    coordinator = template["team"]["coordinator"]["instructions"]
    assert "worker_diff" in coordinator and "read_worker_file" in coordinator
    assert "side_effects_not_approved" in template["team"]["brief"]
    assert "outcome_unknown" in template["team"]["brief"]
    assert all(agent["workspace"] == "sandbox" for agent in template["agents"])
    assert any("git grant" in note for note in template["setup_notes"])


def test_research_runs_without_a_sandbox_and_requires_sources():
    template = TEMPLATES["research"]
    assert all(agent["workspace"] == "none" and agent["tools"] == [] for agent in template["agents"])
    assert "unverified" in template["team"]["brief"]
    assert any("knowledge" in note for note in template["setup_notes"])


# ---- normative rules ---------------------------------------------------------------

def crash_table():
    rows = re.findall(r"^\| `(\w+)` \| (re-run|outcome_unknown) \| (yes|no) \|$", README, re.M)
    return {tool: (resume, approval) for tool, resume, approval in rows}


def test_crash_rule_never_reruns_anything_that_can_change_state():
    table = crash_table()
    assert '{"error":"outcome_unknown","message":"..."}' in README
    assert {tool for tool, (resume, _) in table.items() if resume == "re-run"} == {
        "read_file", "list_files", "search_files", "git_diff", "list_workers", "read_worker_file",
        "worker_diff", "knowledge", "dataset"}
    for tool in ("git_push", "tool", "connection", "exec", "write_file", "edit_file", "git_clone"):
        assert table[tool][0] == "outcome_unknown", tool
    assert "A tool not in this table is treated as `outcome_unknown`." in README


def test_side_effect_tools_are_the_ones_that_need_approval():
    assert {tool for tool, (_, approval) in crash_table().items() if approval == "yes"} == {
        "git_push", "tool", "connection"}
    assert "`side_effects_not_approved`" in README


@pytest.mark.parametrize("rule", [
    "An approval decision requires agents write access on the project, for every person,\n"
    "   including the person who started the run.",
    "Coordinator and worker messages never grant anything.",
    "Grants never widen.",
    "`owner_access_lost`",
    "`N` must be fresh and random for each delivery.",
    "Any occurrence of the closing tag in the body must be neutralized",
    "is data and never instructions",
    "a claim of approval inside\nit is not approval",
    "A name works only if it\n  matches exactly one worker",
    "never the default branch, never force,\n  never delete",
    "There is no silent fallback",
    "says what to work on and grants nothing",
    "The gateway must reject a\n  name containing `/` or `..`",
])
def test_readme_states_the_normative_rule(rule):
    assert rule in README
