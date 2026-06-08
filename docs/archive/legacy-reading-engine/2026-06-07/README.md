# Legacy Reading Engine Archive

This archive was created on 2026-06-07 while restarting LegadoHub around the Python source plugin runtime.

## Why These Files Moved

The active implementation path is now:

- `app/source_plugins/`
- `data/source_plugins/`
- `docs/architecture/source-plugin-contract.md`
- `docs/architecture/plugin-source-runtime-restart-plan.md`
- `docs/superpowers/plans/2026-06-07-stage-1-plugin-engine-shadcn-admin.md`

The files under this archive belong to the previous Reading/Legado compatibility directions:

- Kotlin/JVM direct Reading kernel port.
- Self-written Python Reading rule parser.
- Old server-rendered admin UI.
- Source subscription and rule-engine audit workflow.
- Old verification harness and historical test suites.

They remain available as historical reference, but they must not be imported by active app code or used as the default implementation path.

## Active Boundary

Allowed active dependencies:

- The aggregate Reading/Legado source remains an output compatibility shell.
- `config/source_pool.json` remains active for plugin scheduler concurrency, timeout, proxy, and related runtime settings.
- `app/core/proxy.py` contains the shared proxy decision helper extracted from the old engine path.

Archived-only dependencies:

- `app/engine/`
- `app/legado_engine/`
- `engine-jvm/`
- `app/web/`
- `app/services/source_pool.py`
- `app/services/source_subscriptions.py`
- `app/services/rule_engine_audit.py`
- `app/services/explore_catalog.py`
- `app/services/legado_engine_runner.py`
- `app/services/verification_harness.py`

## Verification Hint

From the repository root, active runtime code should not import old engine modules:

```powershell
rg -n "app\.(engine|legado_engine|web)|from app\.(engine|legado_engine|web)|LegadoEngineRunner|ExploreCatalog|RuleEngineAuditService|SourceSubscriptionService" app tests scripts -S
```

Expected result: no matches outside this archive.
