# Durable runs

Aristotle executes each assistant turn as one DBOS workflow. The public FastAPI
service is the control/read plane; `app.worker` is the only queue consumer. The
browser starts a run with `POST /runs`, receives a stable `run_id`, and reads the
append-only event journal from `/runs/{run_id}/events/stream`. Closing the tab,
changing networks, or losing the stream never cancels execution. Reconnecting
replays from the last event ID.

The run ID is also the DBOS workflow ID. PostgreSQL owns the request, messages,
run status, events, tool-execution journal, steering inputs, and research notes.
DBOS inputs contain only the run ID, so credentials and live HTTP/socket objects
are never serialized into workflow state. Model requests use Pydantic AI's
`DBOSDurability`; custom tool calls are journaled by `(run_id, tool_call_id)`.
Completed results replay without repeating I/O. Recovery fails closed rather
than automatically repeating commands or destructive workspace operations whose
outcome was not recorded.

## Chat controls

- `POST /runs` creates and queues a turn.
- `POST /runs/{run_id}/steer` queues an instruction. The workflow consumes queued
  instructions after the current agent pass and continues in the same run.
- `DELETE /runs/{run_id}` explicitly cancels a run. Merely disconnecting does not.
- `GET /runs/{run_id}` and the event endpoints are safe to poll or replay.

The web client automatically resumes a persisted streaming assistant message
when its conversation is reopened. While a run is active, the composer can add
an instruction or explicitly stop the run.

## Context and compaction

The server ignores browser-supplied history. Before a workflow starts, it loads
only complete user/assistant messages from PostgreSQL, newest-first under
`HISTORY_MAX_MESSAGES` and `HISTORY_MAX_CHARS`, then restores chronological
order as Pydantic `ModelMessage` values. This keeps the prompt below the model's
context window; a larger model window increases how much verbatim history can be
retained but does not replace durable state.

Long investigations should save material findings, decisions, resumable
progress, and source/file/artifact references with the research-note tools.
Active notes are injected under `NOTE_CONTEXT_MAX_CHARS`. Several notes can be
compacted into one summary; the old rows remain linked through `superseded_by`,
so compaction scales without discarding provenance. Notes are working memory,
not automatically current facts, and time-sensitive claims must be refreshed.
The database is canonical; note tools also mirror readable Markdown plus an
active-note index under `.aristotle/notes/` in the conversation sandbox.

## Operations

Production runs three application services: the sleep-managed HTTP backend, an
always-on headless worker, and an always-on sandbox. The worker has no public
port. It emits a database heartbeat and only matching
`DBOS_APPLICATION_VERSION` workers are considered ready. The deployment waits
for all three health checks. Worker search traffic uses the wake-aware public
search route so internal calls cannot let the search service sleep mid-run.

`DATA_RETENTION_DAYS=0` keeps data indefinitely. A positive retention value
removes only inactive conversations and never sweeps queued/running work. Treat
workflow code changes as replay-sensitive: keep compatible workflow and step
names, and bump `DBOS_APPLICATION_VERSION` only with an explicit migration or a
drain of older workflows.
