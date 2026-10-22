# Architecture

This document describes how the contracts repository is organized and how other
Kionga components use it. Read it before you change a schema.

## Bird's-eye view

Kionga components live in separate repositories and share code only through
released packages and this repository. A contract here is a JSON Schema (draft
2020-12) for a document that more than one component reads or writes, plus one
canonical example of that document.

There is one contract today: the pipeline definition, `apiVersion: kionga.dev/v1`,
`kind: Pipeline`. Users write it as YAML or build it in the console's form
editor, and the platform gateway validates it, stores a canonical rendering and
runs it.

## Code map

### `pipeline/v1.schema.json`

The `kionga.dev/v1 Pipeline` schema. Its `$id` is
`https://kionga.dev/schemas/pipeline/v1.json`. Top-level fields are `apiVersion`,
`kind`, `metadata` and `spec`. `spec` holds `nodes` (1 to 200 container or function
steps with `dependsOn`, `when`, `retry`, `resources` and `timeoutSeconds`),
`parameters`, `overridable`, `triggers` (`manual`, `schedule`, `api`, `event`),
`source` and `executionMode` (`prefect` or `functions`). Structural objects set
`additionalProperties: false`, so an unknown or misspelled field fails; free-form
maps such as `parameters` only constrain their key names.

### `pipeline/examples/branched.kionga.yaml`

The canonical example: an extract step, two parallel feature branches (one gated by
a `when` condition), and a training step with GPU resources, retries and a timeout,
on a daily schedule. Both this repository's tests and the platform's Go tests parse
this file.

### `tests/test_pipeline_schema.py`

Validates the example with `jsonschema.Draft202012Validator`, then applies a list of
single mutations (a missing image, a bad node ID, a lowercase `dependson`, a schedule
without cron, a cron macro, too many retries, the wrong `kind`) and asserts that
each one is rejected with an error that names the problem.

### `pyproject.toml`, `requirements-dev.txt`

Test configuration and the pinned ruff rule set (`E4`, `E7`, `E9`, `F`).

## How it connects to other components

- **platform** pins this repository as a Git submodule at `contracts/`. Its Go
  package `pipelinespec` parses and validates pipeline YAML, and
  `TestSharedExampleIsValid` in `go/internal/pipelinespec/spec_test.go` reads
  `contracts/pipeline/examples/branched.kionga.yaml`. Platform CI checks out
  submodules, so a contract change and a validator change meet in one place.
- **pipeline-runner** receives definitions that the gateway has already validated
  and converted to its API form. It does not read the schema.
- **Editors and user CI** reference the schema by tagged URL for completion and
  early structural errors.

## Invariants

- The example is valid under the schema. If you change one, you change the other.
- A published schema file never takes a breaking change. A breaking change is a new
  file (`pipeline/v2.schema.json`) and a new major tag; the old file stays.
- The schema describes structure only. Rules that a JSON Schema cannot express live
  in the platform validator: dependency cycles (reported as a path), dependencies
  on nodes that do not exist, five-field cron expressions and IANA timezones. Users
  must validate against the gateway (`mlaiops pipeline validate` or
  `POST /api/v1/pipelines/validate`) before applying a definition.
- Field names are camelCase, like Kubernetes manifests. The platform maps them to
  its snake_case API types.

## Cross-cutting concerns

- **Versioning.** Tags are `vMAJOR.MINOR.PATCH`. The current tag is `v1.0.0`.
- **Testing.** A schema change without a matching test case is incomplete: add the
  mutation that the new rule rejects.
- **Security gates.** CI runs ruff, pytest, pip-audit, bandit and gitleaks through
  the shared Python workflow. See [CONTRIBUTING.md](CONTRIBUTING.md).
