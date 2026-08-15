# Aristotle

Aristotle is a source-aware AI assistant for research, document analysis, and
sandboxed data work. It combines a streaming chat interface with web search,
uploaded-file tools, Python execution, persistent conversation history, and
primary/fallback model routing.

Aristotle is under active development. Durable run recovery is implemented;
authentication and multi-user access control remain future work.

## What Aristotle can do

- Research current information through SearXNG and return source-backed answers.
- Read, search, quote, summarize, and compare uploaded documents.
- Inspect CSV files, run Python calculations, and generate downloadable charts.
- Stream and replay reasoning, tool activity, sources, and answer text by run ID.
- Persist conversations, messages, runs, events, files, and generated artifacts.
- Use a hosted primary model and fall back to a llama.cpp-compatible model service.

Supported uploads include text, Markdown, JSON, CSV, HTML, PDF, and DOCX files.

## Architecture

```mermaid
flowchart LR
    Web[React web client] -->|HTTP + resumable events| API[FastAPI control plane]
    API --> DB[(PostgreSQL + DBOS queue)]
    Worker[Headless durable worker] --> DB
    Worker --> Primary[Primary model provider]
    Worker --> Fallback[llama.cpp fallback model]
    Worker --> Search[Search service]
    Search --> SearXNG[SearXNG]
    Worker --> Sandbox[Isolated Python sandbox]
    Sandbox --> Artifacts[Generated artifacts]
```

The browser communicates only with the API. The API owns control and reads; the
worker owns execution, recovery, model fallback, and tool orchestration.

The default development command starts the web, API, search, and PostgreSQL
services. The repository's local model container is optional because the API is
configured to use hosted model providers by default.

## Repository layout

| Directory | Responsibility | Documentation |
| --- | --- | --- |
| `web/` | React 19, TypeScript, Vite, and Tailwind chat client | [Web guide](web/README.md) |
| `api/` | FastAPI, Pydantic AI, durable execution, persistence, documents, and workspace orchestration | [API guide](api/README.md), [durable runs](api/docs/durable-runs.md) |
| `sandbox/` | Private code-execution + workspace service (folders, run/build files, presented artifacts) | [Sandbox guide](sandbox/README.md) |
| `search/` | FastAPI wrapper around an internal SearXNG process | [Search guide](search/README.md) |
| `model/` | Dockerized llama.cpp fallback model endpoint | [Model guide](model/README.md) |
| `Makefile` | Local multi-service development orchestration | Run `make help` |

## Quick start

### Prerequisites

- Docker
- Node.js and npm
- GNU Make
- A ModelScope API key for the configured primary model, or access to a working
  OpenAI-compatible provider configured through the model environment variables

Python 3.12 and [`uv`](https://docs.astral.sh/uv/) are also needed when running
or testing the Python services outside Docker.

### 1. Configure the services

Create local environment files from the committed examples:

```sh
cp api/.env.example api/.env
cp search/.env.example search/.env
cp web/.env.example web/.env
```

For the Makefile-managed PostgreSQL container, set these values in `api/.env`:

```env
POSTGRES_PASSWORD=aristotle
DATABASE_URL=postgresql://aristotle:aristotle@aristotle-postgres-dev:5432/aristotle
```

Then add your primary provider credential:

```env
MODELSCOPE_API_KEY=your-token
```

Do not commit local `.env` files. To use another model provider, update
`PRIMARY_MODEL_BASE_URL`, `PRIMARY_MODEL_NAME`, and `PRIMARY_MODEL_API_KEY`.
The fallback provider is controlled by the corresponding `FALLBACK_MODEL_*`
variables.

### 2. Install dependencies and start the stack

```sh
npm --prefix web install
make images
make dev
```

`make dev` reuses the existing local images. Run `make images` again after
changing API, search, or sandbox code or dependencies. Local PostgreSQL data is
kept in the `aristotle-postgres-data-dev` Docker volume across restarts.

The stack exposes:

| Service | Local address |
| --- | --- |
| Web | <http://localhost:5173> |
| API | <http://localhost:8400> |
| API documentation | <http://localhost:8400/docs> |
| Search | <http://localhost:8300> |
| PostgreSQL | `localhost:5433` |

Stop the foreground stack with `Ctrl+C`. The Makefile stops the containers it
started during cleanup.

### 3. Check service health

```sh
curl http://localhost:8400/healthz
curl http://localhost:8400/readyz
curl http://localhost:8400/services
curl http://localhost:8300/healthz
curl http://localhost:8300/readyz
```

`/healthz` reports process liveness. `/readyz` also checks required downstream
services, so it can take longer while a hosted model or search service wakes up.

## Development

### Web

```sh
cd web
npm run dev
npm run lint
npm run build
```

The client reads `VITE_AGENT_HTTP_BASE_URL` and `VITE_AGENT_WS_BASE_URL` from
`web/.env`.

### API

```sh
cd api
uv sync
uv run uvicorn app.main:app --reload --port 8400
```

The API creates chat work at `POST /runs`; the browser resumes it from the run
event stream. `/ws/chat` remains a compatibility delivery route.
See the generated `/docs` page and the [API guide](api/README.md) for details.

### Optional local model

The `model/` image can run a quantized NVIDIA Nemotron GGUF through llama.cpp.
See the [model guide](model/README.md) for build, run, and smoke-test commands.
Point `FALLBACK_MODEL_BASE_URL` at the resulting `/v1` endpoint to use it.

## Verification

```sh
cd web
npm run lint
npm run build
```

```sh
cd api
uv run python -m unittest discover -s tests
uv run python -m app.evals.research tests/evals/research
```

```sh
cd search
uv run python -m unittest discover -s tests
```

## Configuration

The main configuration groups are:

| Group | Important variables |
| --- | --- |
| Primary model | `PRIMARY_MODEL_BASE_URL`, `PRIMARY_MODEL_NAME`, `PRIMARY_MODEL_API_KEY` |
| Fallback model | `MODEL_FALLBACK_ENABLED`, `FALLBACK_MODEL_BASE_URL`, `FALLBACK_MODEL_NAME` |
| Search | `ARISTOTLE_SEARCH_BASE_URL`, `SEARCH_REQUEST_TIMEOUT_SECONDS` |
| Persistence | `DATABASE_URL`, `RESET_DB_ON_START`, `DATA_RETENTION_DAYS` |
| Uploads | `FILE_STORAGE_DIR`, `MAX_UPLOAD_BYTES`, `MAX_PARSED_CHARS` |
| Sandbox | `SANDBOX_ENABLED`, `SANDBOX_RUN_TIMEOUT_SECONDS`, `SANDBOX_ALLOWED_IMPORTS` |
| Web | `VITE_AGENT_HTTP_BASE_URL`, `VITE_AGENT_WS_BASE_URL` |

Refer to [`api/.env.example`](api/.env.example),
[`search/.env.example`](search/.env.example),
[`web/.env.example`](web/.env.example), and
[`model/.env.example`](model/.env.example) for the complete defaults.

## Deployment shape

The services are designed to deploy independently:

- `web/` builds to a static Vite bundle and includes a Vercel SPA rewrite.
- `api/`, `search/`, and `model/` each contain a Dockerfile suitable for any
  container host.
- The API and search edge routes use Sablier; the durable worker and sandbox are
  always on. Worker search calls use the public wake-aware search route.
- Production requires external PostgreSQL. Ephemeral internal PostgreSQL is
  available only with the explicit `ALLOW_EPHEMERAL_DB=true` development flag.
- The frontend should always call the API rather than connecting directly to
  the search or model services.

## Current operational constraints

- The internal PostgreSQL mode is ephemeral and is not durable production storage.
- The search service is currently unauthenticated.
- API CORS defaults to `*`; restrict it before exposing a production deployment.
- The sandbox is designed for Linux and relies on process and system-level limits.
- Data retention is disabled by default (`DATA_RETENTION_DAYS=0`).
- Authentication and multi-user authorization are not currently part of the API.

Use production secrets, durable storage, explicit network policy, and restricted
origins before operating Aristotle with sensitive data.
