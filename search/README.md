---
title: Aristotle Search
emoji: 🔎
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# Aristotle Search Service

SearXNG-backed search tool service for Aristotle.

This Space runs a small FastAPI wrapper in front of an internal SearXNG server. Aristotle's future agent runtime should call the wrapper API, not raw SearXNG, so the agent receives a stable search schema.

## Service Shape

```text
public :7860
  FastAPI wrapper
    GET  /healthz
    GET  /readyz
    POST /search

internal :8080
  SearXNG
    GET /search?format=json
```

## Hosted URL

```text
https://bukunmi2108-aristotle-search.hf.space
```

## Files

```text
Dockerfile
start.sh
pyproject.toml
uv.lock

app/
  main.py       FastAPI routes and lifecycle
  config.py     environment-backed settings
  models.py     request and response schemas
  searxng.py    SearXNG client and response adapter
  url_utils.py  URL cleanup and domain filtering

searxng/
  settings.yml
  limiter.toml
```

## Environment

Defaults are documented in `.env.example`:

```env
PORT=7860
SEARXNG_SETTINGS_PATH=/app/searxng/settings.yml
SEARXNG_INTERNAL_URL=http://127.0.0.1:8080
SEARCH_TIMEOUT_SECONDS=15
SEARXNG_TIMEOUT_SECONDS=12
```

The local `.env` file is for development only and should not be uploaded.

## Local Build

From the repo root:

```sh
docker build -t aristotle-search ./search
```

## Local Run

```sh
docker run --rm --env-file search/.env -p 8300:7860 aristotle-search
```

## Smoke Tests

```sh
curl http://localhost:8300/healthz
curl http://localhost:8300/readyz
```

```sh
curl -X POST http://localhost:8300/search \
  -H "Content-Type: application/json" \
  -d '{"query":"SearXNG JSON API","max_results":5}'
```

## Search Request

```json
{
  "query": "SearXNG JSON API",
  "max_results": 5,
  "language": "en",
  "freshness": "month",
  "domains": ["docs.searxng.org"],
  "category": "general"
}
```

Supported `freshness` values:

```text
day
month
year
```

Supported `category` values:

```text
general
news
science
code
```

`category: "code"` maps to SearXNG's `it` category.

## Search Response

```json
{
  "query": "SearXNG JSON API",
  "results": [
    {
      "title": "Search API - SearXNG Documentation",
      "url": "https://docs.searxng.org/dev/search_api.html",
      "snippet": "SearXNG supports querying via a simple HTTP API...",
      "source": "startpage",
      "published_at": null,
      "score": 16.0
    }
  ],
  "metadata": {
    "elapsed_ms": 1812,
    "result_count": 1,
    "engines": ["duckduckgo", "startpage"]
  }
}
```

## Normalization

The wrapper normalizes raw SearXNG output before returning it:

- keeps only `title`, `url`, `snippet`, `source`, `published_at`, and `score`
- removes common tracking query parameters like `utm_*`, `fbclid`, `gclid`, `msclkid`
- deduplicates by canonical URL
- applies domain post-filtering when `domains` is provided
- caps results to `max_results`

## SearXNG Tuning

`searxng/settings.yml` enables JSON output:

```yaml
search:
  formats:
    - html
    - json
```

Noisy engines seen during local testing are removed:

```yaml
use_default_settings:
  engines:
    remove:
      - ahmia
      - torch
```

`searxng/limiter.toml` is included to avoid missing-config warnings and to define localhost as a trusted proxy.

## Deploy

Create the Space once:

```sh
hf repo create Bukunmi2108/aristotle-search \
  --type space \
  --space-sdk docker \
  --flavor cpu-basic \
  --exist-ok
```

Upload the search folder as the Space root:

```sh
hf upload Bukunmi2108/aristotle-search search . \
  --repo-type space \
  --include 'Dockerfile' \
  --include 'README.md' \
  --include '.dockerignore' \
  --include '.env.example' \
  --include 'pyproject.toml' \
  --include 'uv.lock' \
  --include 'start.sh' \
  --include 'app/*.py' \
  --include 'searxng/**' \
  --commit-message 'Deploy Aristotle search service'
```

Do not upload `.env`, `.venv`, or `__pycache__`.

## Hosted Checks

```sh
curl https://bukunmi2108-aristotle-search.hf.space/healthz
curl https://bukunmi2108-aristotle-search.hf.space/readyz
```

```sh
curl -X POST https://bukunmi2108-aristotle-search.hf.space/search \
  -H "Content-Type: application/json" \
  -d '{"query":"SearXNG JSON API","max_results":5}'
```

## Notes

- This service is intentionally unauthenticated for now.
- The future Aristotle agent API should be the only production caller.
- The frontend should not call this service directly.
- If one upstream search engine rate-limits, SearXNG can still return results from other engines.
