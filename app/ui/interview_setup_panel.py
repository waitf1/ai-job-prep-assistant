from app.ui.styles import panel_heading
import streamlit as st

from app.services.history_interview import build_history_interview_context
from app.services.interview_session import InterviewContext, InterviewSessionService
from app.services.question_bank import extract_question_bank
from app.ui.choices import checkbox_dropdown, one_choice
from app.ui.session_widgets import render_staged_documents


SOURCE_NAMES = {"岗位技术理论": "theory", "简历项目经历": "project", "自选题库": "question_bank"}


def analysis_records(get_history_store):
    try:
        return get_history_store().list_records(kind="analysis")
    except Exception:
        st.warning("历史记录暂时无法读取，可先使用自行上传的资料。")
        return []


def render_modes_and_rounds():
    left, right = st.columns([3, 1])
    with left:
        labels = checkbox_dropdown("面试题目来源", list(SOURCE_NAMES), "interview_sources",
                                   default=["岗位技术理论", "简历项目经历"])
    with right:
        rounds = one_choice("面试轮数", [*range(1, 11), "循环直到自行停止"], "interview_round_limit", default=3)
    return tuple(SOURCE_NAMES[label] for label in labels), rounds


def render_bank(modes):
    if "question_bank" not in modes:
        return []
    with st.container(border=True):
        panel_heading("自选题库")
        documents = render_staged_documents("上传题库或面经（可多选）", "interview_bank",
                                             "只保留在当前会话，不写入资料库。")
        bank = extract_question_bank(documents)
        st.caption(f"已提取 {len(bank)} 道去重题目。")
        return bank


def render_independent_materials(modes, get_history_store, get_resume_store):
    jd_ids, resume_ids, jd_documents, resume_documents = [], [], [], []
    jd_text, resume_text = "", ""
    upload_namespaces = []
    if "theory" in modes:
        with st.container(border=True):
            panel_heading("岗位技术理论 · 岗位 JD")
            methods = checkbox_dropdown("JD 资料来源", ["历史岗位 JD", "自行上传或输入"], "direct_jd_methods")
            if "历史岗位 JD" in methods:
                records = analysis_records(get_history_store)
                names = {r.record_id: f"{r.title} · {r.created_at[:10]}" for r in records}
                jd_ids = checkbox_dropdown("选择历史岗位 JD（可多选）", list(names), "direct_jd_ids", format_func=names.get)
            if "自行上传或输入" in methods:
                upload_namespaces.append("direct_jd")
                jd_documents = render_staged_documents("上传岗位 JD（可多选）", "direct_jd")
                jd_text = st.text_area("补充或粘贴岗位 JD", key="direct_jd_text")
            st.caption("历史 JD 来自已保存的岗位分析；多份 JD 将合并为本次理论题考察范围。")
    if "project" in modes:
        with st.container(border=True):
            panel_heading("简历项目经历 · 完整简历")
            methods = checkbox_dropdown("简历资料来源", ["简历库", "自行上传或输入"], "direct_resume_methods")
            if "简历库" in methods:
                try:
                    records = get_resume_store().list_records()
                except Exception:
                    records = []
                    st.warning("简历库读取失败，请检查资料库或上传完整简历。")
                names = {r.resume_id: r.file_name for r in records}
                resume_ids = checkbox_dropdown("选择完整简历（可多选）", list(names), "direct_resume_ids", format_func=names.get)
            if "自行上传或输入" in methods:
                upload_namespaces.append("direct_resume")
                resume_documents = render_staged_documents("上传完整简历（可多选）", "direct_resume")
                resume_text = st.text_area("补充或粘贴完整简历", key="direct_resume_text")
            st.caption("只依据勾选的真实简历出题；多份简历作为同一候选人的资料合并使用。")

    def build(bank):
        if any(st.session_state.get(f"{namespace}_error") for namespace in upload_namespaces):
            raise ValueError("请先清除解析失败的上传，或重新上传有效文件。")
        jds, resumes = [], []
        for record_id in jd_ids:
            record = get_history_store().get(record_id)
            if record.kind != "analysis" or not isinstance(record.payload.get("job_description"), str):
                raise ValueError("所选历史 JD 不可用，请重新选择。")
            jds.append(record.payload["job_description"])
        for resume_id in resume_ids:
            record = get_resume_store().get(resume_id)
            if not record.text.strip():
                raise ValueError("所选简历没有有效正文。")
            resumes.append(record.text)
        jds.extend(doc.text for doc in jd_documents)
        resumes.extend(doc.text for doc in resume_documents)
        jds.append(jd_text)
        resumes.append(resume_text)
        jd = "\n\n".join(dict.fromkeys(text.strip() for text in jds if text.strip()))
        resume = "\n\n".join(dict.fromkeys(text.strip() for text in resumes if text.strip()))
        context = InterviewContext.from_direct_input(jd, resume, modes, bank)
        InterviewSessionService._validate_question_modes(context)
        return context, None, " ".join(jd.split())[:60] or "独立模拟面试"
    return build


def render_analysis_materials(modes, get_history_store, get_resume_store):
    records = analysis_records(get_history_store)
    names = {r.record_id: f"{r.title} · {r.created_at[:10]}" for r in records}
    if st.session_state.get("latest_workflow_result") is not None:
        names = {"current": "本次岗位分析（当前会话）", **names}
    selected = one_choice("选择岗位分析结果", list(names), "interview_analysis_choice", format_func=names.get)
    options = {}
    if selected and selected != "current" and "project" in modes:
        st.caption("历史不会保存完整简历；沿用原简历时核对内容指纹，也可重新提供简历。")
        method = one_choice("本次面试使用的简历", ["沿用原简历", "选择简历库", "重新上传或输入"],
                            f"analysis_resume_method_{selected}", default="沿用原简历")
        if method == "选择简历库":
            try:
                resumes = get_resume_store().list_records()
            except Exception:
                resumes = []
                st.warning("简历库暂时无法读取。")
            resume_names = {r.resume_id: r.file_name for r in resumes}
            options["replacement_resume_id"] = one_choice("替换简历", list(resume_names), f"analysis_resume_id_{selected}", format_func=resume_names.get)
        elif method == "重新上传或输入":
            documents = render_staged_documents("上传替换简历", f"replacement_{selected}")
            text = st.text_area("重新提供完整简历", key=f"analysis_resume_text_{selected}")
            options["replacement_resume_text"] = "\n\n".join([doc.text for doc in documents] + [text])
        if method in ("选择简历库", "重新上传或输入"):
            options["confirm_replacement"] = st.checkbox("确认使用新简历；内容变化时不沿用旧项目匹配和证据", key=f"analysis_resume_confirm_{selected}")
        options["_method"] = method

    def build(bank):
        if not selected:
            raise ValueError("请先选择一份岗位分析结果。")
        if selected == "current":
            context = InterviewContext.from_workflow_result(st.session_state["latest_workflow_result"], modes, bank)
            return context, st.session_state["analysis_record_id"], st.session_state["analysis_job_description"][:60]
        kwargs = dict(options)
        method = kwargs.pop("_method", "沿用原简历")
        if "project" in modes:
            if method is None:
                raise ValueError("请选择简历来源。")
            if method == "选择简历库" and not kwargs.get("replacement_resume_id"):
                raise ValueError("请选择一份完整简历。")
            if method == "重新上传或输入" and not kwargs.get("replacement_resume_text", "").strip():
                raise ValueError("请重新提供完整简历。")
            if method == "重新上传或输入" and st.session_state.get(f"replacement_{selected}_error"):
                raise ValueError("请先清除解析失败的替换简历。")
        record = get_history_store().get(selected)
        if record.kind != "analysis":
            raise ValueError("请选择岗位分析类型的记录。")
        context = build_history_interview_context(record.payload, modes, bank, resume_store=get_resume_store(), **kwargs)
        return context, record.record_id, record.title
    return build
