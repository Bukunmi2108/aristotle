import ast
import operator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai.tools import RunContext

from app.agent.deps import AgentDeps


class DatetimeResult(BaseModel):
    timezone: str
    iso: str
    date: str
    time: str
    utc_offset: str


class CalculationResult(BaseModel):
    expression: str
    result: str


NUMERIC_OPERATORS: dict[type[ast.operator | ast.unaryop], Callable] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


@dataclass
class UtilityTools(AbstractCapability[AgentDeps]):
    default_timezone: str = "UTC"
    max_expression_chars: int = 500

    def get_instructions(self) -> str:
        return "Use calculate for arithmetic and get_datetime for current dates/times."

    def get_toolset(self) -> FunctionToolset[AgentDeps]:
        toolset = FunctionToolset[AgentDeps](id="utility_tools", strict=False)

        @toolset.tool(name="get_datetime", strict=False)
        async def get_datetime(
            ctx: RunContext[AgentDeps],
            timezone: str | None = None,
        ) -> DatetimeResult:
            """Get the current date and time for an IANA timezone."""
            requested_timezone = timezone or self.default_timezone
            await ctx.deps.events.send(
                "tool.started",
                tool="get_datetime",
                input={"timezone": requested_timezone},
            )
            try:
                tz = ZoneInfo(requested_timezone)
            except ZoneInfoNotFoundError as exc:
                await ctx.deps.events.send(
                    "tool.error",
                    tool="get_datetime",
                    message=f"Unknown timezone: {requested_timezone}",
                )
                raise ValueError(f"Unknown timezone: {requested_timezone}") from exc

            now = datetime.now(tz)
            offset = now.utcoffset() or datetime.now(UTC).utcoffset()
            offset_seconds = int(offset.total_seconds()) if offset is not None else 0
            sign = "+" if offset_seconds >= 0 else "-"
            offset_seconds = abs(offset_seconds)
            hours, remainder = divmod(offset_seconds, 3600)
            minutes = remainder // 60
            return DatetimeResult(
                timezone=requested_timezone,
                iso=now.isoformat(),
                date=now.date().isoformat(),
                time=now.strftime("%H:%M:%S"),
                utc_offset=f"{sign}{hours:02d}:{minutes:02d}",
            )

        @toolset.tool(name="calculate", strict=False)
        async def calculate(
            ctx: RunContext[AgentDeps], expression: str
        ) -> CalculationResult:
            """Evaluate a deterministic arithmetic expression."""
            expression = expression.strip()
            await ctx.deps.events.send(
                "tool.started",
                tool="calculate",
                input={"expression": expression},
            )
            if len(expression) > self.max_expression_chars:
                message = "Expression is too long."
                await ctx.deps.events.send(
                    "tool.error", tool="calculate", message=message
                )
                raise ValueError(message)

            try:
                result = _eval_node(ast.parse(expression, mode="eval").body)
            except Exception as exc:
                await ctx.deps.events.send(
                    "tool.error", tool="calculate", message=str(exc)
                )
                raise

            return CalculationResult(
                expression=expression, result=_format_decimal(result)
            )

        return toolset


def _eval_node(node: ast.AST) -> Decimal:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        try:
            return Decimal(str(node.value))
        except InvalidOperation as exc:
            raise ValueError("Invalid numeric literal.") from exc

    if isinstance(node, ast.BinOp):
        op = NUMERIC_OPERATORS.get(type(node.op))
        if op is None:
            raise ValueError("Unsupported operator.")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 12:
            raise ValueError("Exponent is too large.")
        return op(left, right)

    if isinstance(node, ast.UnaryOp):
        op = NUMERIC_OPERATORS.get(type(node.op))
        if op is None:
            raise ValueError("Unsupported unary operator.")
        return op(_eval_node(node.operand))

    raise ValueError("Only arithmetic expressions are supported.")


def _format_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal(1)))
    return format(normalized, "f")
