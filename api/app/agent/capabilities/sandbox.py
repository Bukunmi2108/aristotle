from dataclasses import dataclass

from pydantic_ai import ToolDefinition
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai.tools import RunContext

from app.agent.deps import AgentDeps
from app.models import SandboxRunResult


SANDBOX_TOOL_NAMES = {"run_python", "inspect_csv", "generate_chart"}
CHART_KINDS = {"line", "bar", "scatter", "hist"}


@dataclass
class SandboxTools(AbstractCapability[AgentDeps]):
    max_input_files: int = 5

    def get_instructions(self):
        def instructions(ctx: RunContext[AgentDeps]) -> str | None:
            if not ctx.deps.sandbox_tools_enabled:
                return None
            return (
                "A local Python sandbox is available for data analysis and chart "
                "generation. Code runs isolated: no network access, no access to "
                "application secrets, and a bounded CPU/memory/time budget. Use "
                "run_python for calculations, filtering, or data transforms instead "
                "of doing arithmetic or data analysis yourself. Always print() "
                "whatever result, value, or summary the user needs — a run that "
                "computes a value but never prints it produces no visible output, "
                "so the answer must come from what the code actually printed, not "
                "from your own mental math. Use inspect_csv to "
                "see column names, types, and summary statistics for an uploaded "
                "CSV before analyzing it. Use generate_chart to create a "
                "downloadable chart image from an uploaded CSV. Reference uploaded "
                "files by their file_id from the attached files list. Any file your "
                "code writes into its working directory becomes a downloadable "
                "artifact automatically — there is no separate save step. If code "
                "fails or times out, report what went wrong instead of guessing at "
                "the output."
            )

        return instructions

    def get_toolset(self) -> FunctionToolset[AgentDeps]:
        toolset = FunctionToolset[AgentDeps](id="sandbox_tools", strict=False)

        @toolset.tool(name="run_python", strict=False)
        async def run_python(
            ctx: RunContext[AgentDeps],
            code: str,
            file_ids: list[str] | None = None,
        ) -> SandboxRunResult:
            """Execute Python code in an isolated local sandbox."""
            await ctx.deps.events.send(
                "tool.started",
                tool="run_python",
                input={"code": code, "file_ids": file_ids or []},
            )
            try:
                selected = self._allowed_file_ids(ctx, file_ids)
                return await _session(ctx).run(code, selected)
            except Exception as exc:
                await ctx.deps.events.send("tool.error", tool="run_python", message=str(exc))
                raise

        @toolset.tool(name="inspect_csv", strict=False)
        async def inspect_csv(
            ctx: RunContext[AgentDeps], file_id: str
        ) -> SandboxRunResult:
            """Inspect an uploaded CSV: columns, dtypes, row count, summary stats."""
            await ctx.deps.events.send(
                "tool.started", tool="inspect_csv", input={"file_id": file_id}
            )
            try:
                selected = self._allowed_file_ids(ctx, [file_id])
                filename = await _resolve_filename(ctx, file_id)
                return await _session(ctx).run(_inspect_csv_code(filename), selected)
            except Exception as exc:
                await ctx.deps.events.send("tool.error", tool="inspect_csv", message=str(exc))
                raise

        @toolset.tool(name="generate_chart", strict=False)
        async def generate_chart(
            ctx: RunContext[AgentDeps],
            file_id: str,
            chart_spec: dict,
        ) -> SandboxRunResult:
            """Generate a downloadable chart image (PNG) from an uploaded CSV.

            chart_spec keys: kind (line|bar|scatter|hist), x, y, title.
            """
            await ctx.deps.events.send(
                "tool.started",
                tool="generate_chart",
                input={"file_id": file_id, "chart_spec": chart_spec},
            )
            try:
                selected = self._allowed_file_ids(ctx, [file_id])
                filename = await _resolve_filename(ctx, file_id)
                code = _generate_chart_code(filename, chart_spec)
                return await _session(ctx).run(code, selected)
            except Exception as exc:
                await ctx.deps.events.send(
                    "tool.error", tool="generate_chart", message=str(exc)
                )
                raise

        return toolset

    def _allowed_file_ids(
        self, ctx: RunContext[AgentDeps], file_ids: list[str] | None
    ) -> list[str]:
        if not file_ids:
            return []
        allowed = set(ctx.deps.file_ids)
        for file_id in file_ids:
            if file_id not in allowed:
                raise ValueError(f"File is not attached to this run: {file_id}")
        return file_ids[: self.max_input_files]

    async def prepare_tools(
        self,
        ctx: RunContext[AgentDeps],
        tool_defs: list[ToolDefinition],
    ) -> list[ToolDefinition]:
        if ctx.deps.sandbox_tools_enabled:
            return tool_defs
        return [tool for tool in tool_defs if tool.name not in SANDBOX_TOOL_NAMES]


def _session(ctx: RunContext[AgentDeps]):
    session = ctx.deps.sandbox_session
    if session is None:
        raise ValueError("Sandbox is not configured for this run.")
    return session


async def _resolve_filename(ctx: RunContext[AgentDeps], file_id: str) -> str:
    store = ctx.deps.document_store
    if store is None:
        raise ValueError("Document persistence is not configured.")
    record = await store.get_file(file_id)
    if record is None:
        raise ValueError(f"Uploaded file not found: {file_id}")
    return record["filename"]


def _inspect_csv_code(filename: str) -> str:
    # `filename` comes from a stored file record, not directly from the model —
    # repr() it into the generated source rather than interpolating raw text,
    # so an unusual filename can't break out of the string literal.
    return (
        "import pandas as pd\n"
        f"df = pd.read_csv({filename!r})\n"
        "print('columns:', list(df.columns))\n"
        "print()\n"
        "print('dtypes:')\n"
        "print(df.dtypes)\n"
        "print()\n"
        "print('row_count:', len(df))\n"
        "print()\n"
        "print('summary:')\n"
        "print(df.describe(include='all'))\n"
    )


def _generate_chart_code(filename: str, chart_spec: dict) -> str:
    kind = chart_spec.get("kind", "line")
    if kind not in CHART_KINDS:
        raise ValueError(f"Unsupported chart kind: {kind!r}. Use one of {sorted(CHART_KINDS)}.")
    x = chart_spec.get("x")
    y = chart_spec.get("y")
    title = chart_spec.get("title") or ""
    if not isinstance(x, str) or not x:
        raise ValueError("chart_spec.x must be a non-empty column name.")
    if kind != "hist" and (not isinstance(y, str) or not y):
        raise ValueError("chart_spec.y must be a non-empty column name for this chart kind.")

    plot_call = (
        f"df.plot(kind={kind!r}, x={x!r}, y={y!r}, ax=ax)"
        if kind != "hist"
        else f"df[{x!r}].plot(kind='hist', ax=ax)"
    )
    return (
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "import pandas as pd\n"
        f"df = pd.read_csv({filename!r})\n"
        "fig, ax = plt.subplots()\n"
        f"{plot_call}\n"
        f"ax.set_title({title!r})\n"
        "fig.tight_layout()\n"
        "fig.savefig('chart.png')\n"
        "print('chart saved to chart.png')\n"
    )
