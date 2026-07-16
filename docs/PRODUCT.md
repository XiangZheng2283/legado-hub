# Product

## Register

product

## Users

LegadoHub has two primary local-network actors:

- An operator who maintains source plugins, official-source authentication, processing health, and recovery workflows.
- A reader who discovers books, manages subscriptions, and follows processing progress in the web console, then reads published chapters in Reading/Legado.

The operator may also be the only reader in a single-user installation, but the product model must not assume that every deployment has only one user.

## Product Purpose

LegadoHub is a self-hosted source-plugin runtime and subscription backend for Reading/Legado. It exposes one importable aggregate source while the web console acts as the subscription and operations control plane for discovery, shared-book ingestion, chapter processing, caching, update tracking, official-source authentication, source governance, proxy fallback, and operator recovery.

Reading/Legado is the primary reading surface. The web console may preview chapter bodies for verification, but it is not a consumer e-reader and must not become the owner of reading position, pagination, typography, themes, or other reading-client behavior.

Success means an operator can keep the source pool healthy and recover failures, while a reader can move through discovery -> subscription -> first readable chapter -> continued reading without understanding plugin internals.

## Active Product Scope

- Source-plugin loading, validation, health checks, and controlled lifecycle management.
- Official-source authentication with explicit, verifiable account state.
- Book discovery and subscription into a shared processed library.
- Deterministic chapter fetch, cleanup, source fallback, integrity checks, and retry.
- Reader and operator views with role-appropriate actions.
- Data integrity, recovery, backup, and operational evidence.

## Explicit Non-Goals

- AI-based chapter proofreading, rewriting, attribution, sensitive-word restoration, or quality scoring.
- Any AI step in the subscription, chapter-processing, or reading critical path.
- Social features, recommendation feeds, billing, or a full consumer e-reader feature set.
- Pixel-level visual refinement while core workflows or verification gates are failing.

Historical AI architecture documents remain reference material only. They do not define the active product roadmap.

## Current Delivery Focus

### Phase 0: Trusted Verification Baseline (Complete)

**Capability:** an operator or contributor can run the documented verification command without modifying real runtime data, and the repository produces one deterministic pass/fail result.

**Required work:**

1. Isolate all backend tests from `backend/data`, the real database, and global runtime services.
2. Update the two current contract-drift assertions and make the effective project suite green.
3. Fix the remaining source-plugin validation failure for `69shuba_tw`.
4. Resolve the high-severity development dependency advisory or document a verified upstream constraint.
5. Remove sensitive browser-console logging from official-source login flows.
6. Define one canonical verification command for backend, frontend, plugins, and runtime smoke.

**Exit criteria:**

- The canonical verification command exits successfully.
- The real database, configuration, and runtime files are unchanged after tests.
- No active plugin fails the repository validator.
- Frontend lint, tests, build, dependency audit, and runtime smoke pass.
- The verification result is reproducible on a clean checkout with documented prerequisites.

Completed on 2026-07-11. The canonical entry point is `verify.ps1` at the repository root.

### Phase 0.5: Critical Workflow Repair (Complete)

- Mobile navigation and removal or completion of non-functional controls.
- User-visible error feedback for search, subscription, library maintenance, and official login.
- Direct navigation to official-source management for administrators.
- Server-side administrator protection for official-source authentication endpoints.
- Deterministic browser-login completion: only an authenticated probe with an explicit account or phone identity is successful.
- Search timeout/expired-job handling, chapter pagination, and shared read-eligibility rules.
- Settings writes are ordered and only clear the dirty state after all changed sections succeed.
- AI proofreading controls and AI-specific chapter-detail fields are hidden from the active product surface; the capability remains a documented non-goal.

Completed on 2026-07-12. Remaining product work moves to Phase 1; this phase deliberately does not add shared-book ownership decoupling or persistent search-job recovery.

### Phase 1: Controlled Subscription Ownership (Active)

Separate the global shared-book entity from a user's personal subscription. The accepted model is one processed shared book with many user subscriptions: readers may discover and manage only their own subscriptions, while shared scheduling, source governance, recovery, rebuild, and deletion remain administrator capabilities.

The visibility, ownership, progress, migration, API, plugin, and release boundaries are fixed in `docs/architecture/subscription-ownership-and-progress-control.zh-CN.md`. Schema work must follow that contract, including the prohibition on deleting an existing database during migration.

### Deferred Until After Phase 1

- Persistent subscription-search lifecycle and recovery.
- Reading-client compatibility improvements that preserve stable source, book, TOC, and chapter contracts.
- Unified data-integrity scan and operator recovery entry point.

## Brand Personality

Quiet, precise, capable. The product should feel like a serious local operations console: clear status, strong evidence, fast diagnosis, and no marketing gloss. The Web backend uses Simplified Chinese as the primary interface language.

## Anti-references

- Generic SaaS landing pages, oversized hero sections, and decorative feature cards.
- AI-purple gradients, glassmorphism as decoration, and ornamental animation.
- Sparse dashboards that hide operational detail behind empty whitespace.
- Over-minimal dashboards that remove useful context in the name of simplicity.
- Fake/demo content that makes parser or source state look better than it is.
- Interfaces that require Reading/Legado app testing for every small parser failure.
- Emoji-based status labels or decorative emoji.

## Design Principles

1. Evidence first: every status must be traceable to a source, URL, phase, timestamp, and error message.
2. Dense but calm: the backend UI should support repeated operational work without feeling cluttered or theatrical.
3. Failures are first-class: disabled plugins, proxy attempts, parser gaps, cache misses, and retry decisions must be visible and actionable.
4. One source of truth: the aggregate source config, plugin progress, source state, and web UI should stay synchronized.
5. Scale from the start: workflows must handle dozens now and thousands later through filtering, batching, pagination, and background jobs.
6. Structure over decoration: visual quality should come from spacing, alignment, dividers, typography, and state hierarchy rather than decorative effects.

## Accessibility & Inclusion

Target WCAG AA contrast for text and controls. The backend UI must support keyboard navigation, visible focus states, reduced-motion preferences, readable tables on desktop, and responsive fallback for narrow screens. Avoid color-only status indicators; pair color with labels or icons.
