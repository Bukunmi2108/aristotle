# Aristotle Search Service

SearXNG-backed search tool service for Aristotle.

This service runs a small FastAPI wrapper in front of an internal SearXNG server. Aristotle's agent runtime calls the wrapper API, not raw SearXNG, so the agent receives a stable search schema.

It is deployed to the Workspace VPS as `workspace-aristotle-search`, behind the shared Caddy gateway with Sablier scale-to-zero. See [`deploy/`](deploy/) and the platform guide in `workspace-infra`.

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
https://aristotle-search.duckdns.org
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

The local `.env` file is for development only and should not be committed.

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

Deployment is automated. On a push to `main` that touches `search/**`, the
[`deploy-search`](../.github/workflows/deploy-search.yml) workflow runs the test
suite, then SSHes to the VPS and invokes the server-side deploy script with the
exact commit:

```text
/opt/workspace/apps/aristotle-search/deploy <git-sha>
```

That script checks out the exact revision, rebuilds only the search container,
and waits for its health check. The production Compose file and deploy script
live in [`deploy/`](deploy/); the gateway route lives in `workspace-infra` at
`gateway/sites/aristotle-search.caddy`.

One-time platform setup (VPS app directory, DuckDNS host, gateway route, GitHub
`production` secrets) follows the `workspace-infra` onboarding workflow.

## Hosted Checks

```sh
curl https://aristotle-search.duckdns.org/healthz
curl https://aristotle-search.duckdns.org/readyz
```

```sh
curl -X POST https://aristotle-search.duckdns.org/search \
  -H "Content-Type: application/json" \
  -d '{"query":"SearXNG JSON API","max_results":5}'
```

## Notes

- This service is intentionally unauthenticated for now.
- The future Aristotle agent API should be the only production caller.
- The frontend should not call this service directly.
- If one upstream search engine rate-limits, SearXNG can still return results from other engines.
