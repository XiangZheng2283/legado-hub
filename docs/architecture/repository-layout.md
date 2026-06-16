# Repository Layout

> **For agentic workers:** Keep the repository root clean. Do not create new backend, plugin, frontend, generated, cache, or test directories at the root unless this document is updated first.

## Root Boundary

The root directory is reserved for project-level control files and four active work areas:

```text
backend/
docs/
frontend/
plugins/
start.bat
.gitattributes
.gitignore
```

## Active Areas

### backend/

FastAPI backend, backend tests, backend scripts, backend configuration, generated aggregate output, and runtime data.

Expected subpaths:

- `backend/app/`: Python application package.
- `backend/config/`: backend-owned JSON configuration.
- `backend/data/`: runtime SQLite/cache data.
- `backend/generated/`: generated Reading/Legado aggregate source output.
- `backend/scripts/`: backend utility scripts.
- `backend/tests/`: backend pytest suite.
- `backend/requirements.txt`: backend Python dependencies.
- `backend/pytest.ini`: backend test configuration.

Run backend commands from `backend/` unless a command explicitly says otherwise.

### frontend/

React/Vite/shadcn/ui console. Keep frontend dependencies, build config, source files, and build output here.

### plugins/

Self-maintained source plugin assets.

Expected subpaths:

- `plugins/sources/`: active Python source plugin directories.
- `plugins/seeds/`: upstream seed snapshots used to create plugins, such as `plugins/seeds/so-novel/`.

Plugins must not own global concurrency, timeout, proxy, retry, cache, or scheduling policy. Those remain backend runtime responsibilities.

### docs/

Current documentation and historical archive.

Expected subpaths:

- `docs/architecture/`: current architecture and boundary documents.
- `docs/superpowers/plans/`: execution plans for agentic workers.
- `docs/archive/`: historical code, source data, old plans, and retired implementation records.

Historical files under `docs/archive/` are reference-only and must not be restored into active paths without an explicit user request.

## Forbidden Root-Level Active Paths

Do not recreate these root paths:

- `app/`
- `config/`
- `data/`
- `generated/`
- `scripts/`
- `tests/`
- `archive/`
- `engine-jvm/`

Use the matching active area instead.

