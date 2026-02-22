# Finance Tooling

Python tooling for monitoring personal finances, starting with import pipelines for
bank statements and expanding toward categorization, reconciliation, and reporting.

## Tech Stack

- `uv` for environment and dependency management
- `ruff` for linting and formatting
- `ty` for static type analysis
- `pre-commit` for local quality gates
- `pytest` for automated tests

## Quick Start

```bash
uv sync --all-groups
uv run python -m finance_tooling
```

## Development Commands

```bash
uv run ruff check .
uv run ruff format .
uv run ty check src/finance_tooling tests
uv run pytest
uv run pre-commit run --all-files
```

## Repository Layout

```text
src/
  finance_tooling/      # new package scaffold
  LBP_API.py            # existing integration script (legacy)
  import_statements.py  # existing parser script (legacy)
tests/
```

## Notes

- Existing scripts are kept as-is and treated as legacy until migrated into
  package modules.
- Lint and type quality gates are currently enforced on the new package scaffold
  (`src/finance_tooling`) while legacy scripts are migrated incrementally.
