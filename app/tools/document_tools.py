from app.services.document_parser import parse_document
from app.tools.base import BaseTool


class ParseDocumentTool(BaseTool):
    name = "parse_document"

    def execute(self, **kwargs):
        file_name = str(kwargs["file_name"])
        file_bytes = kwargs["file_bytes"]
        return parse_document(file_name, file_bytes)

    def summarize_inputs(self, **kwargs) -> str:
        file_name = str(kwargs["file_name"])
        file_bytes = kwargs["file_bytes"]
        return f"file_name={file_name}, bytes={len(file_bytes)}"

    def summarize_output(self, data) -> str:
        return f"parsed_file={data.file_name}, file_type={data.file_type}, text_len={len(data.text)}"
