# OpenUSD Production Inspector

A native Python CLI and library for inspecting OpenUSD stages and generating deterministic scene-health reports.

## Status

Version 0.1 is a read-only validation engine for production asset packages. It reports stage state, composition, references, payloads, sublayers, texture assets, missing dependencies, and six release-gate rules. Every command supports deterministic JSON output and documented process exit codes.

## v0.1

The project scope, non-goals, and acceptance criteria live in the workspace project brief:

`19-projects/active/openusd-production-inspector/PROJECT_BRIEF.md`

## Usage

```powershell
py -3.12 .\scripts\inspect_stage.py ..\openusd-procedural-asset-pipeline\fixtures\valid\industrial-crate\asset.usda summary --format json
py -3.12 .\scripts\inspect_stage.py ..\openusd-procedural-asset-pipeline\fixtures\valid\industrial-crate\asset.usda dependencies --format json
py -3.12 .\scripts\inspect_stage.py ..\openusd-procedural-asset-pipeline\fixtures\valid\industrial-crate\asset.usda composition /Asset --format json
py -3.12 .\scripts\inspect_stage.py ..\openusd-procedural-asset-pipeline\fixtures\valid\industrial-crate\asset.usda validate --format json
py -3.12 -m unittest discover -s tests -v
```

Install the native runtime with `py -3.12 -m pip install --user -r requirements.txt`.

## Layout

- `src/`: package source.
- `tests/`: automated tests and fixtures.
- `examples/`: small valid and invalid USD stages.
- `config/`: local validation-rule configuration.
- `docs/`: architecture and usage documentation.
- `scripts/`: developer tasks.
- `benchmarks/`: performance measurements when justified.

## Exit codes

- `0`: command succeeded, or validation passed
- `1`: validation failed
- `2`: invalid arguments
- `3`: unreadable or malformed stage
- `4`: unexpected internal error

## Constraints

Use native Windows tooling. Do not introduce Docker, WSL, virtual machines, automatic scene mutation, GUI work, or DCC integrations in v0.1.
