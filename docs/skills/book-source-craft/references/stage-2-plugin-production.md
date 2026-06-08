# Stage 2 Plugin Production Workflow

Use this workflow when adapting a new novel source into a LegadoHub Python source plugin.

## Workflow

1. Pick a formal plugin ID from the source domain, for example `qidian_com`; never use `demo_*`.
2. Create the scaffold:

```powershell
cd backend
python scripts/create_source_plugin.py --id example_com --name 示例书源 --domain example.com --base-url https://example.com
```

3. Capture representative search/detail/toc/chapter HTML or JSON.
4. Replace `tests/fixtures/*` and update `tests/smoke.yaml` URLs so they exactly match plugin fetch URLs.
5. Implement `source.py` with `ctx.fetch_text`, `ctx.fetch_json`, `ctx.select`, `ctx.clean_html`, and `ctx.urljoin`.
6. Do not use direct `requests`, `httpx`, unmanaged threads, background tasks, old engines, or Reading rule generation inside the plugin.
7. Validate:

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/example_com
python -m app.source_plugins.smoke ../plugins/sources/example_com --keyword "凡人修仙传"
```

8. Open `/console`, run fixture smoke from the plugin detail page, and inspect diagnostics.
9. If live source behavior is unstable, keep fixture smoke passing and document the live risk in the plugin README.

## AI Adaptation Prompt

```text
Adapt <domain> into a LegadoHub source plugin.
Use plugin contract 1.0.
Do not use requests/httpx directly.
Use ctx.fetch_text/json, ctx.select, ctx.clean_html, ctx.urljoin.
Write fixture smoke for search/detail/toc/chapter.
Return parse diagnostics for empty selectors.
Keep concurrency, timeout, proxy, cache, retry, and Reading aggregate generation in LegadoHub core.
```

## Official Source Preparation

For official sources such as Qidian or Fanqie, set `auth.mode` to `optional`, `required`, or `manual`, fill `loginUrl` and `cookieDomains`, and implement auth hooks only when fixture smoke for public/free flows is already stable.
