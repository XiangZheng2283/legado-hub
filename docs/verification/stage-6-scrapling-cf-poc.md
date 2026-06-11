# Stage 6 Scrapling CF PoC

Date: 2026-06-09

Goal: evaluate whether Scrapling can be used as a temporary Cloudflare bypass
probe for `69shuba_com` without integrating it into LegadoHub.

## Scope

No project runtime code was changed. The test used an isolated virtual
environment under `.tmp/scrapling-poc-venv` and temporary scripts under `.tmp`.

Scrapling installation:

```powershell
python -m venv .tmp/scrapling-poc-venv
.tmp/scrapling-poc-venv/Scripts/python.exe -m pip install scrapling[fetchers] -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
.tmp/scrapling-poc-venv/Scripts/python.exe -m patchright install chromium
```

GitHub clone and default PyPI access failed from this machine due TLS/EOF
transport errors, so the PoC used the PyPI package from the Tsinghua mirror.

## Temporary Scripts

- `.tmp/scrapling_cf_probe.py`
- `.tmp/scrapling_session_probe.py`
- `.tmp/scrapling_search_action_probe.py`

## Scrapling Bypass API Checked

The documented Cloudflare path is:

```python
from scrapling.fetchers import StealthySession

with StealthySession(headless=True, solve_cloudflare=True, timeout=90000) as session:
    page = session.fetch(url)
```

Equivalent single-request usage is:

```python
from scrapling.fetchers import StealthyFetcher

page = StealthyFetcher.fetch(url, headless=True, solve_cloudflare=True, timeout=90000)
```

The installed Scrapling version was `0.4.9`. `StealthyFetcher` uses Patchright
Chromium for the stealth browser path.

## 69shuba Results

These cache-backed pages were readable after decoding GBK/GB2312 response
bodies:

- `https://www.69shuba.com/book/90442.htm`
- `https://www.69shuba.com/book/90442/`
- `https://www.69shuba.com/txt/90442/40755363`

These results appear to be Cloudflare cache hits, not evidence that
`solve_cloudflare=True` bypassed an active challenge.

These challenge-backed pages did not pass:

- `https://www.69shuba.com/newhot_0_1_1.htm`
- `https://www.69shuba.com/modules/article/search.php`

The search page was tested with:

- GET without proxy
- GET with `http://192.168.31.233:7890`
- POST `searchkey=剑宗外门`
- persistent `StealthySession` with a stable `user_data_dir`
- 30 second waits
- `capture_xhr="verify\\.php"`
- browser `page_action` filling the search box and pressing Enter

All search attempts returned a page that still contained:

- `challenges.cloudflare.com/turnstile`
- `cf-turnstile-response`
- `/verify.php` JavaScript callback logic

No `/verify.php` XHR was captured, no `剑宗外门` result appeared, and no
`/book/<id>` search-result link appeared.

## Finding

Scrapling's log can report `Cloudflare captcha is solved` for this embedded
Turnstile page, but the final HTML still contains the Turnstile widget and no
verified search results. In this site flow, the page expects the Turnstile
callback to POST to `/verify.php`, receive a cookie string in `response.data`,
write `document.cookie`, and reload. The PoC did not complete that flow.

## Decision

Do not integrate Scrapling for `69shuba_com` at this point. Continue using
search-provider discovery for 69shuba search, and treat active Turnstile pages
such as site search and ranking pages as bypass-required until a separate,
reliable bypass strategy is proven.
