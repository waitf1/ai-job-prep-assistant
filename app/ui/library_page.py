from app.ui.styles import panel_heading
import streamlit as st
from app.ui.styles import page_intro

from app.services.chunk_reviewer import ChunkReviewer
from app.ui.choices import checkbox_dropdown, one_choice
from app.ui.session_widgets import clear_staged_documents, render_staged_documents


def render_library_page(get_resume_store, get_project_knowledge_base):
    page_intro("资料库", "整理你的经历与项目证据，为岗位分析和模拟面试提供真实依据。", "PERSONAL LIBRARY / 03")
    section = st.radio("资料分类", ["简历库", "项目资料库"], horizontal=True, key="library_section")
    if section == "简历库":
        render_resume_library(get_resume_store)
    else:
        render_project_library(get_project_knowledge_base)


def render_resume_library(get_store):
    st.subheader("简历库")
    st.caption("按全文保存多份简历；使用时可按 JD 自动匹配，也可手动选择。")
    try:
        store = get_store()
        records = store.list_records()
    except Exception as exc:
        st.error(f"简历库读取失败：{exc}")
        return
    feedback = st.session_state.get("resume_library_feedback")
    if feedback:
        st.success(feedback)
    upload_column, preview_column = st.columns([1, 1])
    with upload_column:
        with st.container(border=True):
            panel_heading("添加简历")
            documents = render_staged_documents("上传简历", "resume_library")
            if st.button("添加到简历库", type="primary", disabled=not documents):
                try:
                    result = store.add_documents(documents)
                except Exception as exc:
                    st.error(f"简历入库失败：{exc}")
                else:
                    st.session_state["resume_library_feedback"] = (
                        f"新增 {result.added_resumes} 份简历，跳过 {len(result.skipped_resumes)} 份重复简历。"
                    )
                    clear_staged_documents("resume_library")
                    st.rerun()
    with preview_column:
        with st.container(border=True):
            panel_heading(f"已保存的简历 · {len(records)} 份")
            if not records:
                st.info("上传并添加后，可在岗位分析或模拟面试中选择简历。")
                return
            names = {record.resume_id: record.file_name for record in records}
            selected = one_choice("查看简历", list(names), "library_preview_choice", format_func=names.get)
            if st.button("查看完整简历", disabled=selected is None):
                st.session_state["library_dialog"] = ("preview", selected)
    with st.container(border=True):
        panel_heading("管理与删除")
        selected_ids = checkbox_dropdown("选择要删除的简历", list(names), "library_delete_choices", format_func=names.get)
        if st.button("删除所选简历", disabled=not selected_ids):
            st.session_state["library_dialog"] = ("delete", {key: names[key] for key in selected_ids})
        st.divider()
        st.caption("清空操作会移除库中的全部简历，请谨慎使用。")
        if st.button("清空简历库"):
            st.session_state["library_dialog"] = ("clear", {record.resume_id for record in records})
    dialog = st.session_state.get("library_dialog")
    if dialog:
        action, payload = dialog
        {"preview": show_resume, "delete": confirm_delete_resumes, "clear": confirm_clear_resumes}[action](store, payload)


def close_library_dialog():
    st.session_state.pop("library_dialog", None)


@st.dialog("完整简历", width="large", on_dismiss=close_library_dialog)
def show_resume(store, selected):
    try:
        record = store.get(selected)
        st.caption(record.file_name)
        with st.container(height=500):
            st.text(record.text)
    except Exception:
        st.error("简历暂时无法读取，请关闭后重试。")


@st.dialog("确认删除所选简历", on_dismiss=close_library_dialog)
def confirm_delete_resumes(store, selected):
    st.warning("确定删除以下简历？此操作不可撤销。")
    for name in selected.values():
        st.text(name)
    if st.button("确认删除", type="primary", key="resume_delete_confirm_action"):
        try:
            for resume_id in selected:
                store.delete(resume_id)
        except Exception as exc:
            st.error(f"删除未全部完成，请关闭后检查资料库：{exc}")
        else:
            close_library_dialog()
            st.session_state["library_delete_choices"] = []
            st.session_state["resume_library_feedback"] = f"已删除 {len(selected)} 份简历。"
            st.rerun()
    if st.button("取消", key="resume_delete_cancel"):
        close_library_dialog()
        st.rerun()


@st.dialog("确认清空简历库", on_dismiss=close_library_dialog)
def confirm_clear_resumes(store, original_ids):
    st.warning(f"确定清空全部 {len(original_ids)} 份简历？此操作不可撤销。")
    if st.button("确认清空", type="primary", key="resume_reset_confirm_action"):
        try:
            current_ids = {record.resume_id for record in store.list_records()}
            if current_ids != original_ids:
                st.error("简历库内容已变化，请关闭弹窗后重新确认。")
                return
            store.reset()
        except Exception as exc:
            st.error(f"清空失败：{exc}")
        else:
            close_library_dialog()
            st.session_state["library_delete_choices"] = []
            st.session_state["resume_library_feedback"] = "简历库已清空。"
            st.rerun()
    if st.button("取消", key="resume_reset_cancel"):
        close_library_dialog()
        st.rerun()


def render_project_library(get_kb):
    st.subheader("项目资料库")
    st.caption("上传项目报告、实现说明等补充证据；完整简历请放入简历库。项目资料库可以为空。")
    try:
        kb = get_kb()
        count = kb.count()
    except Exception as exc:
        st.error(f"项目资料库读取失败：{exc}")
        return
    feedback = st.session_state.get("kb_feedback")
    if feedback:
        getattr(st, feedback["level"])(feedback["message"])
        if feedback.get("skipped_documents"):
            with st.expander("查看被跳过的重复文件"):
                for name in feedback["skipped_documents"]:
                    st.text(name)
    with st.container(border=True):
        panel_heading("添加项目资料")
        documents = render_staged_documents("上传项目资料", "project_kb")
        st.session_state.setdefault("enable_ai_review", True)
        enable_review = st.checkbox(
            "使用 AI 复核规则清洗后的全部片段", key="enable_ai_review",
            help="增加入库时的模型调用；审核失败时保守保留原文。",
        )
        if st.button("追加项目库" if count else "建立项目库", type="primary", disabled=not documents):
            progress = st.progress(0, text="正在解析并进行规则清洗...")

            def update_progress(completed, total):
                if total > 0:
                    progress.progress(completed / total, text=f"正在进行 AI 批量审核：第 {completed}/{total} 批")

            with st.spinner("正在清洗、审核并向量化项目资料..."):
                try:
                    reviewer = ChunkReviewer() if enable_review else None
                    result = kb.add_documents(documents, reviewer=reviewer, on_review_progress=update_progress if reviewer else None)
                except Exception as exc:
                    progress.empty()
                    st.error(f"项目资料入库失败：{exc}")
                else:
                    st.session_state["kb_feedback"] = {
                        "level": "success" if result.added_documents else "warning",
                        "message": (
                            f"入库完成：新增 {result.added_documents} 份资料、{result.added_chunks} 个正文片段；"
                            f"规则删除 {result.rule_removed_lines} 行，排除 {result.excluded_sections} 个非正文区段；"
                            f"AI 复核 {result.ai_reviewed_chunks} 个规则保留片段，排除 {result.ai_excluded_chunks} 个，"
                            f"失败保留 {result.ai_review_failed_chunks} 个。"
                        ),
                        "skipped_documents": result.skipped_documents,
                    }
                    clear_staged_documents("project_kb")
                    st.rerun()
    st.caption(f"已保存 {count} 个项目资料片段 · 按来源浏览正文内容")
    if count:
        browse = st.toggle("浏览项目资料片段", key="browse_project_chunks")
        if browse:
            chunks = kb.list_chunks()
            sources = ["全部文件"] + sorted({chunk.source for chunk in chunks})
            if st.session_state.get("library_project_source") not in sources:
                st.session_state.pop("library_project_source", None)
            source = st.selectbox("按来源筛选", sources, key="library_project_source")
            filtered = [chunk for chunk in chunks if source == "全部文件" or chunk.source == source]
            if filtered:
                if st.session_state.get("library_project_chunk", 0) >= len(filtered):
                    st.session_state.pop("library_project_chunk", None)
                index = st.selectbox(
                    "选择片段", range(len(filtered)), key="library_project_chunk",
                    format_func=lambda i: f"{filtered[i].source} | {filtered[i].section_title} | {filtered[i].content_type} | 片段 {filtered[i].chunk_index + 1}",
                )
                with st.container(border=True, height=320):
                    st.text(filtered[index].text)
        with st.expander("管理与删除", expanded=False):
            confirm = st.checkbox("确认清空全部项目资料", key="library_confirm_project_reset")
            if st.button("清空项目资料库", disabled=not confirm):
                try:
                    kb.reset()
                except Exception as exc:
                    st.error(f"清空失败：{exc}")
                else:
                    st.session_state["kb_feedback"] = {"level": "success", "message": "项目资料库已清空。"}
                    st.rerun()
