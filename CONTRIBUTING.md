# Contributing to contracts

Thank you for helping improve Kionga. This repository holds schemas that other
repositories depend on, so every change here is a contract change. Read
[ARCHITECTURE.md](ARCHITECTURE.md) first.

## Development setup

Prerequisites:

- Python 3.11 (the version CI uses)
- Git
- Go, any recent stable release, only if you want to run the gitleaks secret scan
  locally

```bash
git clone git@github.com:kiongahq/contracts.git
cd contracts
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
```

## Run the checks

CI calls the shared Python workflow
([`kiongahq/.github/.github/workflows/python.yml`](https://github.com/kiongahq/.github/blob/main/.github/workflows/python.yml))
with `pip install -r requirements-dev.txt`. Run the same steps locally:

```bash
pip install "ruff>=0.5" "pytest>=8.0"
ruff check .
python -m pytest -q
```

Then the security gates, in the same order and with the same versions:

```bash
pip install --upgrade pip setuptools "pip-audit==2.10.1"
pip-audit --skip-editable                                    # known vulnerabilities in installed packages
pip install "bandit==1.9.4"
bandit -q -r . -x ./tests,./.venv,./node_modules -ll         # medium and higher static findings
go run github.com/zricethezav/gitleaks/v8@v8.30.1 git --no-banner --redact .   # secrets in the full history
```

`tests/test_pipeline_schema.py` checks that the canonical example is valid and that
common structural mistakes are rejected. The ruff rule set is pinned in
`pyproject.toml` so a newer ruff cannot change the gate.

## Change a contract

1. Decide whether the change is compatible. Adding an optional field is compatible.
   Removing or renaming a field, making a field required, or narrowing an allowed
   value is breaking.
2. For a compatible change, edit `pipeline/v1.schema.json` and extend
   `pipeline/examples/branched.kionga.yaml` if the example should show the new field.
   For a breaking change, add `pipeline/v2.schema.json` and leave `v1` published.
3. Add a case to `tests/test_pipeline_schema.py` for each new rule.
4. Update every consumer in the same change set: the Go validator and its tests in
   [platform](https://github.com/kiongahq/platform) (`go/internal/pipelinespec`),
   then move the platform's `contracts` submodule to your commit.
5. After merge, tag a release: `vMAJOR.MINOR.PATCH`, with a new major version for a
   new schema file.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/), as the history
does: `type(scope): summary` in the imperative mood, for example
`feat(pipelines): manual run preflight` or `chore: pin ruff rule set`. Common types
are `feat`, `fix`, `docs`, `test`, `ci` and `chore`.

## Pull requests

- Keep one logical change per pull request.
- CI must pass. Do not skip hooks or checks.
- Link the matching platform pull request when the change affects the validator.

## Reviewed scanner findings

When bandit flags code that you have reviewed and found safe, annotate the line.
Put the reason in a comment on the line before it, and end the flagged line with
`# nosec <rule>` and nothing after it (bandit reads any text after `nosec` as rule
IDs):

```python
# The URL is a fixed https release address.
with urllib.request.urlopen(url, timeout=120) as response:  # nosec B310
```

If a test needs a fake credential that gitleaks reports, add the finding's
fingerprint (`commit:file:rule:line`, printed by gitleaks) to a `.gitleaksignore`
file at the repository root, with a comment that says why. A fingerprint pins one
exact finding, so any new secret still fails the scan.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENCE).
