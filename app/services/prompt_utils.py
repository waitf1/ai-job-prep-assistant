import json
from pathlib import Path


def load_prompt(prompt_dir: Path, file_name: str) -> str:
    return (prompt_dir / file_name).read_text(encoding="utf-8")


def parse_json_response(response_text: str) -> dict:
    candidate = response_text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()

    try:
        result = json.loads(candidate)
        if not isinstance(result, dict):
            raise ValueError("模型输出必须是 JSON 对象。")
        return result
    except json.JSONDecodeError as exc:
        raise ValueError(f"模型输出不是合法 JSON：{exc}") from exc


def ensure_string_list(data: dict, key: str) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"字段 {key} 不是列表。")
    if any(not isinstance(item, str) for item in value):
        raise ValueError(f"字段 {key} 必须是字符串列表。")
    return [item.strip() for item in value if item.strip()]
