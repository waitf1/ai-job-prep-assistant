from pathlib import Path
import sys
import uuid

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.llm.client import LLMConfigError
from app.rag import ProfileKnowledgeBase, ResumeStore
from app.services.interview_session import InterviewSessionService
from app.services.job_prep_workflow import JobPrepWorkflow
from app.storage import HistoryStore
from app.storage.history_snapshots import make_analysis_snapshot, make_interview_snapshot
from app.ui.analysis_result import render_workflow_result
from app.ui.history_panel import render_history_panel
from app.ui.choices import one_choice
from app.ui.interview_setup_panel import (render_modes_and_rounds, render_bank, render_independent_materials, render_analysis_materials)
from app.ui.interview_history import render_interview_history, render_interview_summary
from app.ui.library_page import render_library_page
from app.ui.session_widgets import (
    has_document_input_error, preserve_page_inputs, render_document_input,
)


st.set_page_config(page_title="AI 岗位匹配与面试准备助手", page_icon="AI", layout="wide")

PAGES = ["岗位分析", "模拟面试", "资料库", "历史记录"]
MODE_MAPPING = {"岗位技术理论": "theory", "简历项目经历": "project", "自选题库": "question_bank"}


def reset_interview():
    st.session_state.pop("interview_session", None)
    st.session_state.pop("interview_record_id", None)
    for key in list(st.session_state):
        if key.startswith("interview_answer_"):
            del st.session_state[key]
    st.session_state["interview_generation"] = st.session_state.get("interview_generation", 0) + 1


def go_to(page):
    st.session_state["next_page"] = page
    st.rerun()


def get_history_store():
    # Open only for save/history actions; failure must not block practice.
    return HistoryStore(PROJECT_ROOT / "data" / "history.sqlite3")


def history_title(job_description):
    return " ".join(job_description.split())[:60] or "模拟面试"


def save_history_record(record_id, kind, title, payload, analysis_id=None):
    try:
        store = get_history_store()
        if analysis_id:
            try:
                store.get(analysis_id)
            except KeyError:
                analysis_id = None
        store.save(record_id, kind, title, payload, analysis_id=analysis_id)
    except Exception:
        st.error("保存失败，请检查历史数据库是否被占用或不可写。当前结果仍在页面中，可稍后重试保存。")
    else:
        st.success("已保存到本地历史；重复点击会更新同一条记录。")


def prepare_history_interview(analysis_id):
    st.session_state["interview_context_choice"] = ["通过岗位分析结果进行面试"]
    st.session_state["interview_analysis_choice"] = [analysis_id]
    go_to("模拟面试")


@st.cache_resource(show_spinner=False)
def get_project_knowledge_base():
    return ProfileKnowledgeBase(persist_dir=PROJECT_ROOT / "data" / "vector_store", collection_name="project_documents")


@st.cache_resource(show_spinner=False)
def get_resume_store():
    return ResumeStore(storage_dir=PROJECT_ROOT / "data" / "resumes", index_persist_dir=PROJECT_ROOT / "data" / "vector_store")


def render_profile_inputs():
    mode = st.radio(
        "分析模式", ["普通分析模式", "RAG 资料库模式"], horizontal=True, key="analysis_mode",
        help="普通模式使用临时简历；RAG 模式从简历库选择一份完整简历。",
    )
    use_rag = mode == "RAG 资料库模式"
    preferred_id = None
    left, right = st.columns(2)
    with left:
        st.html('<div class="input-heading">个人经历 · 简历与资料</div>')
        if use_rag:
            try:
                records = get_resume_store().list_records()
            except Exception as exc:
                records = []
                st.error(f"简历库读取失败：{exc}")
            names = {record.resume_id: record.file_name for record in records}
            options = ["__auto__"] + list(names)
            if st.session_state.get("preferred_resume_option") not in options:
                st.session_state.pop("preferred_resume_option", None)
            selected = st.selectbox(
                "本次使用的简历", options, key="preferred_resume_option", disabled=not records,
                format_func=lambda value: "系统按岗位自动选择" if value == "__auto__" else names[value],
            )
            preferred_id = None if selected == "__auto__" else selected
            if not records:
                st.info("简历库为空，请到「资料库」添加完整简历。")
            else:
                st.caption(f"已保存 {len(records)} 份完整简历。独立项目面试未提供 JD 时，请手动选择一份。")
            st.text_area("补充说明（可选）", key="supplementary_note", height=150,
                         placeholder="本次希望强调的经历、求职方向或限制条件。")
        else:
            render_document_input("上传简历 / 项目资料", "resume_text", "resume_file", "上传文件或粘贴完整简历。")
            st.caption("临时输入仅用于当前会话；可在资料库中另行保存简历。")
    with right:
        st.html('<div class="input-heading">目标方向 · 岗位 JD</div>')
        render_document_input("上传岗位 JD", "job_description", "jd_file", "上传文件或粘贴目标岗位的招聘描述。")
    return use_rag, preferred_id


def run_analysis(use_rag, preferred_id):
    if has_document_input_error(use_rag):
        st.warning("请先处理上传文件的解析错误：移除失败文件，或编辑保留的文本后重试。")
        return
    job_description = st.session_state.get("job_description", "")
    resume_text = st.session_state.get("resume_text", "")
    if not job_description.strip():
        st.warning("请先输入岗位 JD。")
        return
    if not use_rag and not resume_text.strip():
        st.warning("普通分析模式下请先输入简历内容。")
        return
    with st.spinner("正在执行 Agent 工作流，请稍候..."):
        try:
            if use_rag and not get_resume_store().list_records():
                st.warning("RAG 模式需要至少一份完整简历。请先到资料库添加简历。")
                return
            workflow = JobPrepWorkflow(
                resume_store=get_resume_store() if use_rag else None,
                project_knowledge_base=get_project_knowledge_base() if use_rag else None,
            )
            result = workflow.run(
                resume_text=st.session_state.get("supplementary_note", "").strip() if use_rag else resume_text,
                job_description=job_description, use_rag=use_rag, preferred_resume_id=preferred_id,
            )
        except LLMConfigError as exc:
            st.error(f"模型配置不完整：{exc}")
            return
        except Exception as exc:
            st.error(f"分析失败：{exc}")
            return
    st.session_state["latest_workflow_result"] = result
    st.session_state["latest_analysis_is_rag"] = use_rag
    st.session_state["analysis_record_id"] = uuid.uuid4().hex
    st.session_state["analysis_job_description"] = job_description
    st.session_state["analysis_snapshot"] = None
    try:
        source_text = get_resume_store().get(result.selected_resume.resume_id).text if result.selected_resume else resume_text
        st.session_state["analysis_snapshot"] = make_analysis_snapshot(result, job_description, use_rag, source_text)
    except Exception:
        st.session_state["analysis_snapshot_warning"] = True
    else:
        st.session_state.pop("analysis_snapshot_warning", None)
    st.rerun()


def render_analysis_page():
    page_intro("岗位分析", "从你的经历出发，找到与目标岗位的连接。上传资料后，查看匹配结论、简历建议与面试准备。", "CAREER WORKSPACE / 01")
    result = st.session_state.get("latest_workflow_result")
    with st.container(border=True):
        section_heading("01", "分析资料与设置")
        use_rag, preferred_id = render_profile_inputs()
        if st.button("开始岗位分析", type="primary"):
            run_analysis(use_rag, preferred_id)
    if result is None:
        return
    st.caption("本次分析岗位：" + history_title(st.session_state.get("analysis_job_description", "")))
    save_column, interview_column = st.columns(2)
    with save_column:
        if st.button("保存本次分析", disabled=st.session_state.get("analysis_snapshot") is None):
            save_history_record(st.session_state["analysis_record_id"], "analysis",
                                history_title(st.session_state["analysis_job_description"]), st.session_state["analysis_snapshot"])
    with interview_column:
        if st.button("去模拟面试", type="primary"):
            st.session_state["interview_context_choice"] = ["通过岗位分析结果进行面试"]
            st.session_state["interview_analysis_choice"] = ["current"]
            go_to("模拟面试")
    if st.session_state.get("analysis_snapshot_warning"):
        st.warning("本次结果可查看，但简历引用无法核对，暂不能保存历史。请重新分析后保存。")
    render_workflow_result(result, st.session_state.get("latest_analysis_is_rag", False))


def render_interview_page():
    page_intro("模拟面试", "把准备变成练习。逐轮回答、获得反馈，结束后保存面试复盘。", "INTERVIEW PRACTICE / 02")
    session = st.session_state.get("interview_session")
    if session is not None:
        st.caption("本场面试：" + st.session_state.get("interview_title", "模拟面试"))
        if st.button("返回岗位分析"):
            go_to("岗位分析")
        render_interview_session(session)
        return
    from app.ui.choices import context_switch
    entry = context_switch()
    if not entry:
        st.info("请选择面试上下文。")
        return
    with st.container(border=True):
        panel_heading("面试设置")
        modes, round_choice = render_modes_and_rounds()
        if entry == "独立面试":
            build = render_independent_materials(modes, get_history_store, get_resume_store)
        else:
            build = render_analysis_materials(modes, get_history_store, get_resume_store)
        bank = render_bank(modes)
        if st.button("开始模拟面试", type="primary"):
            try:
                if round_choice is None:
                    raise ValueError("请选择面试轮数或循环模式。")
                if "question_bank" in modes and st.session_state.get("interview_bank_error"):
                    raise ValueError("请先清除解析失败的题库上传。")
                context, analysis_id, title = build(bank)
                with st.spinner("正在生成首个面试问题..."):
                    session = InterviewSessionService().start(
                        context, max_rounds=None if round_choice == "循环直到自行停止" else round_choice,
                    )
            except (ValueError, KeyError) as exc:
                st.warning(f"无法启动模拟面试：{exc}")
            except Exception as exc:
                st.error(f"启动模拟面试失败：{exc}")
            else:
                st.session_state["interview_session"] = session
                st.session_state["interview_analysis_id"] = analysis_id
                st.session_state["interview_title"] = title
                st.rerun()


def render_interview_session(session):
    if session.status == "active":
        st.markdown(f"**第 {session.current_round_number} 轮 · {str(session.max_rounds) + ' 轮计划' if session.max_rounds is not None else '循环练习'}**")
        if session.max_rounds is not None:
            st.progress(len(session.rounds) / session.max_rounds)
        labels = {value: key for key, value in MODE_MAPPING.items()}
        st.caption("本题来源：" + labels.get(session.current_question_source, session.current_question_source))
        st.info(session.current_question)
        answer_key = f"interview_answer_{st.session_state.get('interview_generation', 0)}_{session.current_round_number}"
        answer = st.text_area("你的回答", key=answer_key, height=220,
                              placeholder="像真实面试一样组织回答；没有相关经历时可如实说明。")
        submit_column, finish_column, restart_column = st.columns(3)
        with submit_column:
            submit = st.button("提交回答并继续", type="primary")
        with finish_column:
            finish = st.button("结束并生成复盘", disabled=not session.rounds)
        with restart_column:
            restart = st.button("重新开始")
        if submit:
            with st.spinner("正在评价回答并生成后续问题..."):
                try:
                    InterviewSessionService().submit_answer(session, answer)
                except Exception as exc:
                    if session.status == "summary_pending":
                        st.rerun()
                    st.error(f"本轮面试处理失败：{exc}")
                else:
                    st.rerun()
        if finish:
            with st.spinner("正在生成面试复盘..."):
                try:
                    InterviewSessionService().finish(session)
                except Exception:
                    st.rerun()
                else:
                    st.rerun()
        if restart:
            reset_interview()
            st.rerun()
    elif session.status == "summary_pending":
        st.warning("回答与反馈已保存，复盘尚未生成成功。请重试生成复盘，无需重新提交回答。")
        if st.button("重试生成复盘", type="primary"):
            try:
                InterviewSessionService().finish(session)
            except Exception as exc:
                st.error(f"生成面试复盘失败：{exc}")
            else:
                st.rerun()
    else:
        st.success("本次模拟面试已结束。")
        if session.summary is not None:
            render_interview_summary(session.summary)
            if st.button("保存本次复盘"):
                record_id = st.session_state.setdefault("interview_record_id", uuid.uuid4().hex)
                save_history_record(record_id, "interview", st.session_state.get("interview_title", "模拟面试"),
                                    make_interview_snapshot(session), st.session_state.get("interview_analysis_id"))
        if st.button("重新开始一场模拟面试"):
            reset_interview()
            st.rerun()
    render_interview_history(session.rounds)


preserve_page_inputs()
for key in ("resume_text", "job_description", "supplementary_note"):
    st.session_state.setdefault(key, "")
next_page = st.session_state.pop("next_page", None)
if next_page in PAGES:
    st.session_state["navigation"] = next_page

from app.ui.styles import apply_styles, page_intro, section_heading, panel_heading
apply_styles()
with st.container(key="top_navigation"):
    brand, menu, spacer = st.columns([1, 3, 1], vertical_alignment="center")
    with brand:
        st.markdown("**✦ 求职准备助手**")
    with menu:
        page = st.radio("功能导航", PAGES, key="navigation", horizontal=True, label_visibility="collapsed")



if page == "岗位分析":
    render_analysis_page()
elif page == "模拟面试":
    render_interview_page()
elif page == "资料库":
    render_library_page(get_resume_store, get_project_knowledge_base)
else:
    page_intro("历史记录", "回看每一次分析与练习，让下一次准备更有方向。", "YOUR PROGRESS / 04")
    render_history_panel(
        get_history_store, render_workflow_result, prepare_history_interview,
    )
