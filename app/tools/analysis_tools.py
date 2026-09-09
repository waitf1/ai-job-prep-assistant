from app.services.interview_preparer import InterviewPreparer
from app.services.jd_analyzer import JDAnalyzer
from app.services.resume_advisor import ResumeAdvisor
from app.tools.base import BaseTool


class AnalyzeJobDescriptionTool(BaseTool):
    name = "analyze_job_description"
    description = "分析岗位 JD，提取岗位职责、必备技能、加分项和 AI 关键词。"

    def __init__(self, analyzer: JDAnalyzer) -> None:
        self.analyzer = analyzer

    def execute(self, **kwargs):
        job_description = str(kwargs["job_description"])
        return self.analyzer.analyze(job_description)

    def summarize_inputs(self, **kwargs) -> str:
        job_description = str(kwargs["job_description"])
        return f"job_description_len={len(job_description)}"

    def summarize_output(self, data) -> str:
        return (
            f"responsibilities={len(data.responsibilities)}, "
            f"required_skills={len(data.required_skills)}, "
            f"bonus_points={len(data.bonus_points)}"
        )

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "job_description": {
                    "type": "string",
                    "description": "用户输入的岗位 JD 原文。",
                }
            },
            "required": ["job_description"],
        }


class GenerateResumeAdviceTool(BaseTool):
    name = "generate_resume_advice"
    description = "根据岗位要求、匹配结果和个人资料生成简历修改建议。"

    def __init__(self, advisor: ResumeAdvisor) -> None:
        self.advisor = advisor

    def execute(self, **kwargs):
        return self.advisor.analyze(
            resume_text=str(kwargs["resume_text"]),
            jd_analysis=kwargs["jd_analysis"],
            match_analysis=kwargs["match_analysis"],
            retrieved_context=str(kwargs.get("retrieved_context", "")),
        )

    def summarize_inputs(self, **kwargs) -> str:
        resume_text = str(kwargs["resume_text"])
        return (
            f"resume_len={len(resume_text)}, "
            f"matched_points={len(kwargs['match_analysis'].matched_points)}, "
            f"gaps={len(kwargs['match_analysis'].gaps)}"
        )

    def summarize_output(self, data) -> str:
        return f"direct_edits={len(data.direct_edits)}, future_edits={len(data.future_edits)}"

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "resume_text": {"type": "string", "description": "简历正文或补充说明。"},
                "retrieved_context": {"type": "string", "description": "检索到的资料库片段文本。"},
            },
            "required": ["resume_text"],
        }


class GenerateInterviewQuestionsTool(BaseTool):
    name = "generate_interview_questions"
    description = "根据岗位要求和个人资料生成针对性面试问题与短期补强建议。"

    def __init__(self, preparer: InterviewPreparer) -> None:
        self.preparer = preparer

    def execute(self, **kwargs):
        return self.preparer.analyze(
            resume_text=str(kwargs["resume_text"]),
            jd_analysis=kwargs["jd_analysis"],
            match_analysis=kwargs["match_analysis"],
            retrieved_context=str(kwargs.get("retrieved_context", "")),
        )

    def summarize_inputs(self, **kwargs) -> str:
        resume_text = str(kwargs["resume_text"])
        return (
            f"resume_len={len(resume_text)}, "
            f"required_skills={len(kwargs['jd_analysis'].required_skills)}, "
            f"gaps={len(kwargs['match_analysis'].gaps)}"
        )

    def summarize_output(self, data) -> str:
        return f"questions={len(data.questions)}, short_term_focus={len(data.short_term_focus)}"

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "resume_text": {"type": "string", "description": "简历正文或补充说明。"},
                "retrieved_context": {"type": "string", "description": "检索到的资料库片段文本。"},
            },
            "required": ["resume_text"],
        }
