# Repository Guidelines

## Project Structure & Module Organization

`src/main/code/scalp_lab/` contains the research engines, market-data feeds, IC Markets/MT5 integration, decision history, and automation code. `src/main/code/dashboard.py` is the active GOLD/XAUUSD Streamlit interface; `src/main/code/dashboard_legacy.py` preserves the older multi-asset interface. `src/test/code/tests/test_*.py` covers the corresponding modules. `README.md` explains setup, while `GOLD_RESEARCH.md` records the active strategy, validation results, and limitations. Root `.venv` and `.env` hold the ignored local environment and credentials; `lib/` holds ignored journals, locks, history, and research output.

## Build, Test, and Development Commands

On Windows, install and launch with the checked-in wrappers:

```powershell
.\install.cmd
.\run.cmd
.\.venv\Scripts\python.exe -m unittest discover -s src/test/code/tests -v
```

The PowerShell implementations are `install.ps1` and `run.ps1`; `run.cmd -Check` performs a preflight without launching. The last command above runs the full test suite. `install.cmd -ResearchOnly` skips the Windows-only MT5 connector for legacy CLI research.

## Coding Style & Naming Conventions

Use four spaces for indentation in new Python code. Follow nearby module conventions, but keep new functions and variables in `snake_case`, classes in `PascalCase`, and constants in `UPPER_CASE`. Keep market-data transformations causal: a decision must use only information available at its timestamp. No formatter or linter is configured; keep edits focused and readable.

## Testing Guidelines

Tests use standard-library `unittest`, with files named `test_<module>.py` and methods named `test_<behavior>`. Add regression tests for changed signal logic, news gates, storage, and trade execution paths. Mock broker and network calls; do not require live credentials or a running MT5 terminal. There is no stated coverage percentage requirement.

## Commit & Pull Request Guidelines

The short Git history contains only generic initial-commit messages, so it does not establish a naming convention. Use a concise imperative subject that identifies the affected area, such as `Fix gold exit timing`. In pull requests, describe the behavior change, test command and result, and any effect on trading or historical validation. Include dashboard screenshots for UI changes and link an issue when one exists.

## Security & Configuration

Keep credentials in local `.env` files and never add new secrets to code, examples, logs, or research artifacts. Older commits contain configuration and generated files; check staged diffs carefully and treat any previously exposed keys as compromised. Automatic entries are subject to the documented validation and news gates; preserve those checks when changing automation.
