"""Producer-to-gateway ingest contracts are open: a newer producer's extra field
never invalidates a step report, log batch or trace (docs/compatibility.md).

Every fixture under ingest/examples/<contract>/ is valid; extra-field.json adds
properties the schema does not list, at the top level and in nested objects.
Known properties are still typed, so an open contract is not an untyped one."""

import copy
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
INGEST = ROOT / "ingest"
CONTRACTS = {"step-report": "step-report.v1.schema.json", "log-batch": "log-batch.v1.schema.json", "trace": "trace.v1.schema.json"}


def schema(name):
    return json.loads((INGEST / CONTRACTS[name]).read_text())


def errors(name, document):
    validator = jsonschema.Draft202012Validator(schema(name), format_checker=jsonschema.FormatChecker())
    return [error.message for error in validator.iter_errors(document)]


FIXTURES = sorted((name, path) for name in CONTRACTS for path in (INGEST / "examples" / name).glob("*.json"))


def test_every_ingest_schema_is_well_formed():
    for name in CONTRACTS:
        jsonschema.Draft202012Validator.check_schema(schema(name))


@pytest.mark.parametrize("name,path", FIXTURES, ids=lambda value: getattr(value, "name", value))
def test_fixtures_are_valid(name, path):
    assert errors(name, json.loads(path.read_text())) == []


@pytest.mark.parametrize("name", CONTRACTS)
def test_each_contract_has_an_extra_field_fixture_with_unknown_properties(name):
    document = json.loads((INGEST / "examples" / name / "extra-field.json").read_text())
    known = set(schema(name)["properties"])
    assert set(document) - known, f"{name}/extra-field.json adds no unknown top-level field"


def test_log_entries_accept_unknown_fields_too():
    document = json.loads((INGEST / "examples" / "log-batch" / "extra-field.json").read_text())
    entry_fields = set(schema("log-batch")["$defs"]["entry"]["properties"])
    assert set(document["entries"][0]) - entry_fields


@pytest.mark.parametrize("name", CONTRACTS)
def test_unknown_fields_at_any_depth_are_accepted(name):
    document = json.loads((INGEST / "examples" / name / "minimal.json").read_text())
    document["added_by_a_newer_producer"] = {"nested": [1, 2, 3]}
    if name == "log-batch":
        document["entries"][0]["added_by_a_newer_producer"] = True
    assert errors(name, document) == []


@pytest.mark.parametrize("name,field,value", [
    ("step-report", "status", "done"),
    ("step-report", "attempt", "two"),
    ("step-report", "step", ""),
    ("trace", "input_tokens", -1),
    ("trace", "agent_id", 7),
    ("log-batch", "entries", {"node": "x", "message": "y"}),
])
def test_known_fields_stay_typed(name, field, value):
    document = copy.deepcopy(json.loads((INGEST / "examples" / name / "minimal.json").read_text()))
    document[field] = value
    assert errors(name, document), f"{name}.{field}={value!r} should be rejected"


@pytest.mark.parametrize("name,field", [("step-report", "step"), ("step-report", "status"), ("trace", "agent_id"),
                                        ("trace", "session_id"), ("log-batch", "entries")])
def test_required_fields_match_the_gateway(name, field):
    document = json.loads((INGEST / "examples" / name / "minimal.json").read_text())
    del document[field]
    assert any(field in message for message in errors(name, document))


def test_step_statuses_match_the_gateway():
    # platform go/internal/store/store.go validStepStatus
    assert schema("step-report")["properties"]["status"]["enum"] == ["pending", "running", "succeeded", "failed", "skipped"]


def test_log_batch_size_matches_the_gateway():
    # platform go/internal/httpapi/logs.go maxIngestEntries
    assert schema("log-batch")["properties"]["entries"]["maxItems"] == 500
    batch = {"entries": [{"node": "n", "message": "m"}] * 501}
    assert errors("log-batch", batch)
