# Product

## Register

product

## Users

LegadoHub is used by a local power user who manages Reading/Legado book sources on a Windows machine and accesses the service from Reading/Legado on phone or LAN devices. The primary context is operational: inspecting source health, debugging parser failures, tuning proxy behavior, validating search/detail/toc/content flows, and keeping a large source pool usable without hand-editing every rule.

## Product Purpose

LegadoHub is a local aggregation middleware for Reading/Legado. It exposes one importable aggregate source to the Reading app while the local service handles search, detail, TOC, chapter content, caching, update tracking, source governance, proxy fallback, and later AI-assisted cleanup. Success means a user can import one source, search and read reliably, see why a source failed, and recover broken or restricted sources without leaving the web backend.

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
3. Failures are first-class: disabled sources, proxy attempts, parser gaps, cache misses, and retry decisions must be visible and actionable.
4. One source of truth: the aggregate source config, parser progress, source state, and web UI should stay synchronized.
5. Scale from the start: workflows must handle dozens now and thousands later through filtering, batching, pagination, and background jobs.
6. Structure over decoration: visual quality should come from spacing, alignment, dividers, typography, and state hierarchy rather than decorative effects.

## Accessibility & Inclusion

Target WCAG AA contrast for text and controls. The backend UI must support keyboard navigation, visible focus states, reduced-motion preferences, readable tables on desktop, and responsive fallback for narrow screens. Avoid color-only status indicators; pair color with labels or icons.
