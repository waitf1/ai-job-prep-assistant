from app.rag import DEFAULT_RETRIEVAL_CANDIDATE_LIMIT, ProfileKnowledgeBase
from app.tools.base import BaseTool


class SearchProjectKnowledgeBaseTool(BaseTool):
    name = "search_project_knowledge_base"
    description = "从项目资料库中检索与当前岗位最相关的项目实现和经历证据。"

    def __init__(self, knowledge_base: ProfileKnowledgeBase) -> None:
        self.knowledge_base = knowledge_base

    def execute(self, **kwargs):
        query = str(kwargs["query"])
        candidate_limit = int(kwargs.get("candidate_limit", DEFAULT_RETRIEVAL_CANDIDATE_LIMIT))
        return self.knowledge_base.search(query, top_k=candidate_limit)

    def summarize_inputs(self, **kwargs) -> str:
        query = str(kwargs["query"])
        candidate_limit = int(kwargs.get("candidate_limit", DEFAULT_RETRIEVAL_CANDIDATE_LIMIT))
        return f"query={self._shorten(query)}, candidate_limit={candidate_limit}"

    def summarize_output(self, data) -> str:
        return f"retrieved_chunks={len(data)}"

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "用于检索项目资料库的查询语句，应概括岗位要求和需要补充的项目实现证据。",
                },
            },
            "required": ["query"],
        }


SearchProfileKnowledgeBaseTool = SearchProjectKnowledgeBaseTool
