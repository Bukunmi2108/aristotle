---
title: Aristotle API
emoji: 🧠
colorFrom: yellow
colorTo: red
sdk: docker
app_port: 7860
pinned: false
---

# Aristotle Agent API

Agent orchestration layer for Aristotle.

The frontend should talk only to this API. The API wakes the model/search Spaces,
runs the Pydantic AI agent, exposes tool activity, and streams reasoning/output
events back to the client.

## Services

```text
aristotle-api
  /                 service metadata
  /healthz          process health
  /readyz           model/search readiness
  /services         model/search status
  /ws/chat          chat WebSocket

primary inference provider
  https://api-inference.modelscope.ai/v1/models
  https://api-inference.modelscope.ai/v1/chat/completions

fallback aristotle-model
  /v1/models
  /v1/chat/completions

aristotle-search
  /readyz
  /search
```

## Agent Runtime

The chat runtime uses Pydantic AI, not a separate research endpoint. The agent
prompt, model settings, retries, metadata, built-in capabilities, and custom
tool capabilities live in `app/agent/specs/aristotle.yaml`.

```text
client WebSocket
  -> Aristotle API
    -> wake/check model
    -> Pydantic AI agent run_stream_events()
      -> optional LocalWebTools capability call
        -> wake/check search
        -> Aristotle Search /search
        -> optional fetch_url
      -> optional UtilityTools capability call
        -> get_datetime / calculate
      -> llama.cpp OpenAI-compatible /v1/chat/completions
  -> streamed websocket events
```

Web search tools are available automatically. The model decides when to call
them during the response.

The primary provider is ModelScope API Inference using `zai-org/GLM-5.2`. The
fallback is the existing llama.cpp OpenAI-compatible Space. Both are wrapped
with OpenAI-compatible Pydantic AI profiles that map streamed
`reasoning_content` into thinking events. The runtime falls back on quota, rate
limit, timeout, and provider/server errors.

Custom capabilities are normal Pydantic AI `AbstractCapability` subclasses loaded
from YAML with `custom_capability_types`. Each related tool group owns its
`FunctionToolset`:

```yaml
capabilities:
  - LocalWebTools:
      max_search_results: 5
      max_fetch_bytes: 200000
      max_fetch_chars: 12000
  - UtilityTools:
      default_timezone: Africa/Lagos
      max_expression_chars: 500
```

Runtime-owned pieces stay in Python because they depend on process state:

```text
app/agent/specs/aristotle.yaml   prompt, settings, capabilities
app/agent/capabilities/          YAML-loadable capability classes
app/agent/factory.py             primary/fallback model provider wiring
app/agent/runtime.py             event-stream translation
```

## WebSocket Events

Typical event sequence:

```text
session.started
service.checking
service.ready
agent.started
reasoning.delta
tool.started
service.checking
service.ready
tool.result
reasoning.delta
message.delta
message.completed
session.completed
```

Tool events can happen in the middle of the response, not only before the final
answer starts.

## Local Run

```sh
uv sync
uv run uvicorn app.main:app --reload --port 8400
```

## Docker

```sh
docker build -t aristotle-api ./api
docker run --rm --env-file api/.env -p 8400:7860 aristotle-api
```

## Smoke Checks

```sh
curl http://localhost:8400/
curl http://localhost:8400/healthz
curl http://localhost:8400/services
```

## Research Evals

Offline research fixtures live in `tests/evals/research`. They validate event
traces for protocol and integrity checks: tool usage, tool inputs, source
domains, source counts, failed source previews, citation marker resolution,
hallucinated raw URLs, duplicate raw citation sections, and event-derived
runtime metrics.

```sh
uv run python -m app.evals.research tests/evals/research
```

To run the same fixture expectations against a live API WebSocket, start the API
separately and run:

```sh
uv run python -m app.evals.live_research \
  --ws-url ws://localhost:8400/ws/chat \
  --fixtures tests/evals/research \
  --runs 3
```

## Model Provider Environment

```sh
PRIMARY_MODEL_BASE_URL=https://api-inference.modelscope.ai/v1
PRIMARY_MODEL_NAME=zai-org/GLM-5.2
MODELSCOPE_API_KEY=...
MODEL_FALLBACK_ENABLED=true
FALLBACK_MODEL_BASE_URL=https://bukunmi2108-aristotle-model.hf.space/v1
FALLBACK_MODEL_NAME=/models/NVIDIA-Nemotron3-Nano-4B-Q4_K_M.gguf
FALLBACK_MODEL_API_KEY=unused
```

## WebSocket Message

```json
{
  "type": "user.message",
  "message": "Use search if needed, then answer clearly.",
  "options": {
    "max_search_results": 5
  }
}
```
