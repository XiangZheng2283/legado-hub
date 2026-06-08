# Legacy Engine Archive

> **For agentic workers:** This document marks the old engine paths as archived historical reference only. Do not build new features on these paths.

## Active Direction

The current active runtime is the **Python source plugin runtime** defined in:

- `docs/architecture/plugin-source-runtime-restart-plan.md`
- `docs/architecture/source-plugin-contract.md`
- `backend/app/source_plugins/`

## Legacy Code Paths

| Path | Role | Status |
|---|---|---|
| `docs/archive/legacy-reading-engine/2026-06-07/engine-jvm/` | Kotlin/JVM direct port of upstream Reading kernel | Archived. Do not extend. |
| `docs/archive/legacy-reading-engine/2026-06-07/app/legado_engine/` | Self-written Python Reading rule parser | Archived. Do not extend. |
| `docs/archive/legacy-reading-engine/2026-06-07/app/engine/` | Early experimental Python parser scaffold | Archived. Do not extend. |
| `docs/archive/legacy-reading-engine/2026-06-07/app/web/` | Old server-rendered console/debug UI | Archived. React console is the active UI path. |

## Legacy Docs

| Document | Status |
|---|---|
| `docs/archive/legacy-reading-engine/2026-06-07/docs/architecture/legadohub-redesign-roadmap.md` | Superseded on 2026-06-07. |
| `docs/archive/legacy-reading-engine/2026-06-07/docs/architecture/legadohub-phase-1-kernel-port-plan.md` | Historical reference for the JVM port direction. |
| `docs/archive/legacy-reading-engine/2026-06-07/docs/implementation-plan-full-legado-backend.md` | Historical reference for the pre-port backend plan. |
| `docs/archive/legacy-reading-engine/2026-06-07/docs/upstream-legado-rule-semantics.md` | Reference-only for understanding upstream semantics. |
| `docs/archive/legacy-reading-engine/2026-06-07/docs/verification/phase-1-direct-kernel-port.md` | Historical verification record. |

## Allowed Reference-Only Uses

- Understanding common source patterns from `app/legado_engine/`
- Migration input for creating Python source plugins
- Optional future "legacy Reading source import" feature

## Forbidden Stage 1 Uses

- Do not instantiate `LegadoEngineRunner` in active catalog/search paths.
- Do not import `app.legado_engine`, `app.engine`, or `engine-jvm` in new plugin code.
- Do not treat Reading rule execution as the primary runtime.
- Do not add new features to the Kotlin/JVM engine.

## Verification: No Active Catalog Path Imports Legacy Runner

Run this command to confirm no active service/API imports the legacy runner:

```powershell
rg -n "LegadoEngineRunner|app\.legado_engine|app\.engine|engine-jvm|AnalyzeRule|Kotlin|JVM" backend/app/services backend/app/api -S
```

Expected: no active-path matches. Historical matches may exist under `docs/archive/legacy-reading-engine/2026-06-07/`.
