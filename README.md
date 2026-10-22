# contracts

[![CI](https://github.com/kiongahq/contracts/actions/workflows/ci.yml/badge.svg)](https://github.com/kiongahq/contracts/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENCE)

Versioned schemas that the Kionga components agree on.

## Background

Kionga is a self-hosted platform for machine learning, data and AI agents. Its
components live in separate repositories, so any document that more than one of
them reads needs a single, versioned definition. This repository holds those
definitions. Today it publishes one contract: the `kionga.dev/v1 Pipeline`
definition, a JSON Schema for the YAML files you use to describe a pipeline as a
graph of containers.

The [platform](https://github.com/kiongahq/platform) pins this repository as a Git
submodule and validates every pipeline definition before it stores or runs it.

## Install

Nothing to install. Reference the schema by its tagged URL:

```text
https://raw.githubusercontent.com/kiongahq/contracts/v1.0.0/pipeline/v1.schema.json
```

## Usage

Add the schema to a pipeline file to get completion and inline errors in any editor
that uses the YAML language server:

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/kiongahq/contracts/v1.0.0/pipeline/v1.schema.json
apiVersion: kionga.dev/v1
kind: Pipeline
metadata:
  name: churn-training
  project: prj-example
  version: "1"
spec:
  nodes:
    - id: train
      type: container
      image: ghcr.io/acme/churn:1.4.0
      command: [python, -m, churn.train]
```

[`pipeline/examples/branched.kionga.yaml`](pipeline/examples/branched.kionga.yaml)
is a complete example with parallel branches, a condition, retries, resources and a
schedule.

The schema checks structure only. Before you apply a definition, validate it
against a running gateway, which also rejects dependency cycles, dependencies on
missing nodes, and invalid cron expressions or timezones:

```bash
mlaiops pipeline validate churn.kionga.yaml
```

## Documentation

- Product documentation: [Pipelines](https://kiongahq.github.io/docs/guides/pipelines/)
  and the [CLI reference](https://kiongahq.github.io/docs/reference/cli/)
- Engineering handbook: <https://kiongahq.github.io/docs/engineering/>
- How this repository is laid out: [ARCHITECTURE.md](ARCHITECTURE.md)

## Contributing

A change here is a contract change. Read [CONTRIBUTING.md](CONTRIBUTING.md) before
you open a pull request.

## License

[MIT](LICENCE) © Kionga contributors
