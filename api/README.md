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

aristotle-model
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

`options.use_search=false` builds the agent without search tools.
`options.use_search=true` gives the model a `search_web` tool and lets the model
decide when to call it during the response.

The llama.cpp model is wrapped with a custom OpenAI profile so Pydantic AI sends
compatible request fields and maps streamed `reasoning_content` into thinking
events.

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
app/agent/factory.py             model provider and custom capability wiring
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

## WebSocket Message

```json
{
  "type": "user.message",
  "message": "Use search if needed, then answer clearly.",
  "options": {
    "use_search": true,
    "max_search_results": 5
  }
}
```
