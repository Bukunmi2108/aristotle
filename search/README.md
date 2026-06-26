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

## Endpoints

```text
GET  /healthz
GET  /readyz
POST /search
```

## Local Build

```sh
docker build -t aristotle-search ./search
```

## Local Run

```sh
docker run --rm -p 8300:7860 aristotle-search
```

## Smoke Test

```sh
curl http://localhost:8300/healthz
curl http://localhost:8300/readyz

curl -X POST http://localhost:8300/search \
  -H "Content-Type: application/json" \
  -d '{"query":"SearXNG JSON API","max_results":5}'
```

The service exposes a normalized Aristotle schema instead of raw SearXNG JSON.
