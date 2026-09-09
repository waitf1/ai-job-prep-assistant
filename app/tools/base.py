from typing import Any

from app.tools.tool_types import ToolResult


class BaseTool:
    name = "base_tool"
    description = "Base tool"

    def run(self, **kwargs) -> ToolResult:
        input_summary = self.summarize_inputs(**kwargs)
        try:
            data = self.execute(**kwargs)
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=data,
                input_summary=input_summary,
                output_summary=self.summarize_output(data),
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                input_summary=input_summary,
                output_summary="",
                error_message=str(exc),
            )

    def execute(self, **kwargs) -> Any:
        raise NotImplementedError

    def summarize_inputs(self, **kwargs) -> str:
        return ", ".join(f"{key}={self._shorten(value)}" for key, value in kwargs.items())

    def summarize_output(self, data: Any) -> str:
        return self._shorten(data)

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.get_parameters_schema(),
            },
        }

    @staticmethod
    def _shorten(value: Any, limit: int = 120) -> str:
        text = str(value)
        text = " ".join(text.split())
        if len(text) <= limit:
            return text
        return f"{text[:limit]}..."
