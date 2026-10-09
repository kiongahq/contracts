# contracts

The versioned schemas that Kionga components agree on. A change here is a contract
change: bump the version, then update every consumer.

| Contract | File | Consumers |
| --- | --- | --- |
| Pipeline definition `kionga.dev/v1 Pipeline` | [`pipeline/v1.schema.json`](pipeline/v1.schema.json) | [platform](https://github.com/kiongahq/platform) (Go validator, `internal/pipelinespec`, tests against the same example); editors and CI in user projects. The [pipeline-runner](https://github.com/kiongahq/pipeline-runner) receives definitions the platform has already validated. |

[`pipeline/examples/`](pipeline/examples/) holds canonical documents. The schema test
here checks the example is valid and that structural mistakes are rejected, and the
platform's Go tests parse the same example, so both sides agree on one document.

The JSON Schema covers structure. The platform validator also rejects what a schema
cannot express (cycles, dependencies on missing nodes, invalid cron or timezone), so
always validate with `kionga pipeline validate` or `POST /api/v1/pipelines/validate`
before applying a definition.

## Use

The platform pins this repo as a Git submodule at `contracts/`. Editors can reference
the schema directly:

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/kiongahq/contracts/v1.0.0/pipeline/v1.schema.json
```

## Versioning

Tags are `vMAJOR.MINOR.PATCH`. A breaking schema change gets a new file
(`pipeline/v2.schema.json`) and a major version; `v1` stays published.

## Develop

```bash
pip install -r requirements-dev.txt
python -m pytest -q && ruff check .
```
