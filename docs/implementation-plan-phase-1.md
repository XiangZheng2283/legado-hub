# Phase 1 Implementation Plan

> **For Kimi:** Implement this plan task-by-task. Do not skip validation. Do not commit or push unless the user explicitly asks.

**Goal:** Build a Windows-runnable local FastAPI skeleton for LegadoHub that can start by double-clicking `start.bat`, expose health/API metadata, and generate the first importable aggregate source JSON shell.

**Architecture:** Use a small Python FastAPI app with focused modules for configuration, API routes, source generation, and storage initialization. Keep business logic minimal in phase 1; prepare stable interfaces for phase 2 parsing and Web UI.

**Tech Stack:** Python 3.12+, FastAPI, Uvicorn, Pydantic, SQLite standard library, pytest.

---

## File Map

- Create `requirements.txt`: runtime and test dependencies.
- Create `start.bat`: Windows launcher that creates `.venv`, installs dependencies, and starts the service.
- Create `app/__init__.py`: package marker.
- Create `app/main.py`: FastAPI app factory and route registration.
- Create `app/config.py`: project paths, host, port, app metadata.
- Create `app/api/__init__.py`: API package marker.
- Create `app/api/health.py`: health and metadata endpoints.
- Create `app/api/legado.py`: placeholder Legado-facing endpoints for source JSON and API contract.
- Create `app/core/__init__.py`: core package marker.
- Create `app/core/source_generator.py`: generate first aggregate source shell.
- Create `app/storage/__init__.py`: storage package marker.
- Create `app/storage/db.py`: SQLite path and initialization.
- Create `tests/test_health.py`: health endpoint tests.
- Create `tests/test_source_generator.py`: source generator tests.
- Modify `docs/project-plan.md`: record phase 1 implementation artifacts if paths change.

## API Contract for Phase 1

Phase 1 must expose:

- `GET /health`
- `GET /api/info`
- `GET /api/legado/source`
- `GET /api/legado/search`
- `GET /api/legado/book/{book_id}`
- `GET /api/legado/book/{book_id}/toc`
- `GET /api/legado/chapter/{chapter_id}`

Only `/health`, `/api/info`, and `/api/legado/source` need real behavior in phase 1. Other endpoints may return structured placeholder responses with `implemented: false`, so the interface shape is reserved for phase 2.

## Task 1: Project Runtime Skeleton

**Files:**

- Create `requirements.txt`
- Create `app/__init__.py`
- Create `app/config.py`
- Create `app/main.py`
- Create `app/api/__init__.py`
- Create `app/api/health.py`
- Create `tests/test_health.py`

**Required behavior:**

- App imports without side effects.
- `GET /health` returns service status.
- `GET /api/info` returns name, version, phase, and project paths.
- Tests pass with `pytest`.

**Acceptance commands:**

```powershell
python -m pip install -r requirements.txt
python -m pytest tests/test_health.py -v
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Expected:

- Tests pass.
- Uvicorn starts without import errors.
- `http://127.0.0.1:8765/health` returns JSON with `status: ok`.

## Task 2: SQLite Initialization

**Files:**

- Create `app/storage/__init__.py`
- Create `app/storage/db.py`
- Modify `app/main.py`
- Add or extend tests.

**Required behavior:**

- Ensure `data/app.db` exists on startup.
- Create minimal tables:
  - `schema_meta`
  - `source_registry`
  - `books`
  - `chapters`
  - `update_tasks`
- Do not require external database services.

**Acceptance commands:**

```powershell
python -m pytest tests -v
python -c "from app.storage.db import initialize_database; print(initialize_database())"
```

Expected:

- Tests pass.
- `data/app.db` exists.
- Initialization can run repeatedly without error.

## Task 3: Aggregate Source Generator

**Files:**

- Create `app/core/__init__.py`
- Create `app/core/source_generator.py`
- Create `tests/test_source_generator.py`
- Modify `app/api/legado.py`
- Modify `app/main.py`

**Required behavior:**

- Generate a JSON array with one Legado source object.
- Output includes:
  - `bookSourceName`
  - `bookSourceGroup`
  - `bookSourceUrl`
  - `bookSourceType`
  - `enabled`
  - `enabledCookieJar`
  - `enabledExplore`
  - `header`
  - `searchUrl`
  - `ruleSearch`
  - `ruleBookInfo`
  - `ruleToc`
  - `ruleContent`
  - `jsLib`
- Generated source should call LegadoHub endpoints, not external upstream sites.
- Save generated file to `generated/legadohub-source.json`.
- `GET /api/legado/source` returns the same JSON.

**Acceptance commands:**

```powershell
python -m pytest tests/test_source_generator.py -v
python -c "from app.core.source_generator import write_aggregate_source; print(write_aggregate_source())"
python docs/skills/book-source-craft/scripts/inspect_legado_source.py generated/legadohub-source.json
```

Expected:

- Tests pass.
- Generated JSON is valid.
- Inspect script reports one source with all key modules.

## Task 4: Placeholder Legado API Endpoints

**Files:**

- Create or modify `app/api/legado.py`
- Add tests for route shape.

**Required behavior:**

- Search endpoint returns:

```json
{
  "implemented": false,
  "items": [],
  "message": "Search parser will be implemented in phase 2"
}
```

- Book, toc, and chapter endpoints return structured placeholders with consistent field names.
- No endpoint raises a 500 for normal placeholder requests.

**Acceptance commands:**

```powershell
python -m pytest tests -v
```

Expected:

- All route-shape tests pass.

## Task 5: Windows Launcher

**Files:**

- Create `start.bat`
- Optionally create `.gitignore` if generated local artifacts need exclusion.

**Required behavior:**

- Double-clicking `start.bat` should:
  - create `.venv` if missing
  - install `requirements.txt`
  - start `uvicorn app.main:app --host 127.0.0.1 --port 8765`
- The terminal stays open on failure.

**Acceptance commands:**

```powershell
cmd /c start.bat
```

Expected:

- Server starts on `127.0.0.1:8765`.
- Browser can open `/health`.

## Task 6: Documentation Update

**Files:**

- Modify `docs/project-plan.md`
- Create `docs/phase-1-verification.md`

**Required behavior:**

Document:

- Startup steps.
- Generated source path.
- Health check URL.
- Placeholder endpoint list.
- What is intentionally not implemented until phase 2.

## AI Self-Test Procedure

Kimi must run this self-test before reporting completion. The self-test is part of the deliverable, not optional.

### 1. Static File Check

Verify required files exist:

```powershell
@'
from pathlib import Path
required = [
    "requirements.txt",
    "start.bat",
    "app/__init__.py",
    "app/main.py",
    "app/config.py",
    "app/api/__init__.py",
    "app/api/health.py",
    "app/api/legado.py",
    "app/core/__init__.py",
    "app/core/source_generator.py",
    "app/storage/__init__.py",
    "app/storage/db.py",
    "tests/test_health.py",
    "tests/test_source_generator.py",
    "docs/phase-1-verification.md",
]
missing = [p for p in required if not Path(p).exists()]
print("missing:", missing)
raise SystemExit(1 if missing else 0)
'@ | python -
```

Expected: `missing: []`.

### 2. Automated Tests

Run all tests:

```powershell
python -m pytest tests -v
```

Expected: all tests pass.

If tests fail, Kimi must fix the failure or report the exact failing test and reason.

### 3. Database Initialization Test

Run:

```powershell
python -c "from app.storage.db import initialize_database; print(initialize_database())"
```

Expected:

- Command exits successfully.
- `data/app.db` exists.
- Re-running the command succeeds again.

### 4. Source Generation Test

Run:

```powershell
python -c "from app.core.source_generator import write_aggregate_source; print(write_aggregate_source())"
python docs/skills/book-source-craft/scripts/inspect_legado_source.py generated/legadohub-source.json
```

Expected:

- `generated/legadohub-source.json` exists.
- Inspect output includes `source_count: 1`.
- Inspect output includes non-missing `searchUrl`, `ruleSearch`, `ruleBookInfo`, `ruleToc`, `ruleContent`, and `jsLib`.

### 5. Server Smoke Test

Start server:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

In another terminal, run:

```powershell
@'
import json
from urllib.request import urlopen

urls = [
    "http://127.0.0.1:8765/health",
    "http://127.0.0.1:8765/api/info",
    "http://127.0.0.1:8765/api/legado/source",
    "http://127.0.0.1:8765/api/legado/search?keyword=test",
    "http://127.0.0.1:8765/api/legado/book/test-book",
    "http://127.0.0.1:8765/api/legado/book/test-book/toc",
    "http://127.0.0.1:8765/api/legado/chapter/test-chapter",
]

for url in urls:
    with urlopen(url, timeout=10) as response:
        body = response.read().decode("utf-8")
        print(url, response.status, body[:300].replace("\n", "\\n"))
        if response.status != 200:
            raise SystemExit(1)
        json.loads(body)
'@ | python -
```

Expected:

- Every endpoint returns HTTP 200.
- Every response is valid JSON.
- `/health` includes `status: ok`.
- Placeholder APIs include `implemented: false`.

### 6. Launcher Test

Run:

```powershell
cmd /c start.bat
```

Expected:

- It creates `.venv` if missing.
- It installs dependencies from `requirements.txt`.
- It starts the server on `127.0.0.1:8765`.
- On failure, terminal remains open or prints actionable error output.

If this test is difficult to run because it starts a foreground process, Kimi must at least run the script once and report what happened.

### 7. Self-Review Checklist

Before final response, Kimi must check:

- No code depends on Docker.
- No code implements full Web management UI.
- No code deletes or overwrites `data/sources/reference/光遇聚合26.6.2.json`.
- Generated source is a single-source JSON array.
- Placeholder APIs do not pretend real parsing is implemented.
- `docs/phase-1-verification.md` documents what is implemented and what is deferred.

## Final Phase 1 Acceptance

Kimi must report:

1. Full file change list.
2. Exact commands run.
3. Test results.
4. Health endpoint output.
5. Generated source inspect output.
6. Any unresolved issues.

Codex will review against this plan and decide whether Phase 1 is accepted.
