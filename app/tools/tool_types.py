from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolCallRecord:
    tool_name: str
    input_summary: str
    output_summary: str
    success: bool
    error_message: str = ""


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    success: bool
    data: Any = None
    input_summary: str = ""
    output_summary: str = ""
    error_message: str = ""

    def to_record(self) -> ToolCallRecord:
        return ToolCallRecord(
            tool_name=self.tool_name,
            input_summary=self.input_summary,
            output_summary=self.output_summary,
            success=self.success,
            error_message=self.error_message,
        )


@dataclass
class ToolExecutionContext:
    records: list[ToolCallRecord] = field(default_factory=list)

    def add_result(self, result: ToolResult) -> None:
        self.records.append(result.to_record())
