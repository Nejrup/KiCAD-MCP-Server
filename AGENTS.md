# AGENTS.md
Agent operating guide for `KiCAD-MCP-Server`.

Grounded sources in this repo:
- `package.json`
- `tsconfig.json`
- `pytest.ini`
- `.github/workflows/ci.yml`
- `src/index.ts`, `src/server.ts`, `src/logger.ts`
- `python/kicad_interface.py`, `python/commands/*.py`

## 1) Stack and Boundaries
- Mixed architecture: TypeScript MCP server + Python KiCAD backend.
- TS compiles to `dist/` and runs as Node ESM (`dist/index.js`).
- Python bridge script: `python/kicad_interface.py`.
- Responsibility split:
  - TS: MCP registration, request validation/shaping, subprocess orchestration.
  - Python: KiCAD operations and command-domain logic.
- When adding features end-to-end, update both TS and Python sides.

## 2) Setup
Run from repo root:
```bash
npm ci
python -m pip install -r requirements.txt
python -m pip install black mypy flake8 pytest pytest-cov
```
Useful env vars:
- `KICAD_PYTHON` (override Python executable)
- `KICAD_BACKEND` (backend mode selection)
- `KICAD_AUTO_LAUNCH` (KiCAD UI launch behavior)

## 3) Build Commands
```bash
npm run build
npm run build:watch
npm run clean
npm run rebuild
npm run start
npm run dev
```
Script meanings (`package.json`):
- `build`: `tsc`
- `build:watch`: `tsc --watch`
- `start`: `node dist/index.js`
- `dev`: watch build + nodemon

## 4) Lint and Format Commands
```bash
npm run lint
npm run lint:ts
npm run lint:py
npm run format
```
Notes:
- `lint:ts` currently has fallback `|| echo ...` when ESLint config is missing.
- `lint:py` runs `black`, `mypy`, `flake8` inside `python/`.
- `format` runs Prettier for TS and Black for Python.

## 5) Test Commands
```bash
npm test
npm run test:py
npm run test:coverage
pytest tests/ -v
pytest python/test_ipc_backend.py -v
```
Current status:
- Python tests are real and runnable.
- `npm run test:ts` is a placeholder echo (no TS test runner configured yet).

## 6) Single-Test Execution (Important)
Preferred direct pytest targeting:
```bash
# single file
pytest tests/test_platform_helper.py -v

# single class
pytest tests/test_platform_helper.py::TestPlatformDetection -v

# single test
pytest tests/test_platform_helper.py::TestPlatformDetection::test_exactly_one_platform_detected -v

# by marker or name filter
pytest -m integration -v
pytest -k "platform_name" -v
```
NPM pass-through form:
```bash
npm run test:py -- tests/test_platform_helper.py::TestPlatformDetection::test_exactly_one_platform_detected -v
npm run test:py -- -k "exactly_one_platform_detected"
```

## 7) TypeScript Style Rules
- Keep NodeNext ESM conventions (`tsconfig.json`).
- Respect strict typing (`strict: true`); avoid weakening types.
- Prefer explicit parameter/return types for exported APIs.
- Prefer `unknown` + narrowing over broad `any`.
- Keep relative import paths with `.js` suffix in TS source (repo pattern).
- Naming:
  - `PascalCase`: classes/types/interfaces.
  - `camelCase`: functions/methods/variables.
  - `SCREAMING_SNAKE_CASE`: constants.
- Error handling:
  - Use `try/catch` at process, I/O, and external-boundary edges.
  - Keep structured error payload patterns where existing modules use them.
  - Never swallow exceptions silently.
- Logging:
  - Use `src/logger.ts` logger.
  - Keep MCP stdout clean; logs go to stderr/files.

## 8) Python Style Rules
- Keep formatting Black-compatible.
- Use type annotations (`Dict[str, Any]`, `Optional[...]`, etc.).
- Naming:
  - `snake_case`: functions/variables.
  - `PascalCase`: classes.
  - `UPPER_SNAKE_CASE`: constants.
- Preserve command response shape in handlers:
  - `success`, `message`, `errorDetails`.
- Log exceptions with context before returning failure responses.
- Keep domain structure intact:
  - `python/commands/`, `python/schemas/`, `python/resources/`.

## 9) Agent Workflow
Before editing:
1. Read nearby files and match local patterns.
2. Check if change crosses TS/Python boundary.
3. Prefer small, focused edits.
After editing:
1. Run `npm run build`.
2. Run targeted tests (pytest single-test first when possible).
3. Run relevant lint/format commands.
4. Report exact commands and outcomes.

## 10) CI Signals to Mirror
CI (`.github/workflows/ci.yml`) validates:
- TS build and lint path
- Python quality checks (format/type/lint)
- Python tests with coverage
Mirror the relevant subset for touched files.

## 11) Known Quirks
- `pytest.ini` includes `testpaths = tests python/tests`, but `python/tests` may be absent.
- Additional Python test exists at `python/test_ipc_backend.py`.
- Some npm scripts use `|| echo ...`; do not treat those as comprehensive validation.
