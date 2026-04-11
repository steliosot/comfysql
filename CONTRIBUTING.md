# Contributing

Thanks for your interest in contributing to ComfySQL.

## Quick Start

1. Fork the repository and create a feature branch.
2. Set up a virtual environment.
3. Install in editable mode.
4. Run tests before opening a PR.

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m pytest -q tests/test_cli_unit.py tests/test_sql_engine.py
```

## Development Guidelines

- Keep changes focused and minimal.
- Prefer `comfysql` in docs/examples (`comfy-agent` remains a compatibility alias).
- Use `input/assets` for local media inputs.
- Avoid committing secrets/tokens or personal local config.
  - `comfy-agent.json` is intentionally gitignored.

## Commit and PR

- Use clear commit messages.
- Include what changed and why.
- If behavior changes, update docs (`README.md`, `COMMANDS.md`, `STARTERS.md`) in the same PR.
- Add or update tests when relevant.

## Reporting Issues

When opening issues, include:

- command used
- full CLI output
- expected behavior vs actual behavior
- environment details (OS, Python version, local/remote server mode)

## Code of Conduct

By participating in this project, you agree to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

