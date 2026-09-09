"""Keep editable inputs and parsed uploads available while their page is hidden."""

import hashlib

import streamlit as st

from app.services.document_parser import DocumentParseError, parse_document


DOCUMENT_TYPES = ["pdf", "docx", "txt", "md", "markdown"]


def preserve_page_inputs():
    # Streamlit cleans up widget values when the widget is not rendered. An
    # explicit assignment detaches these editable values from that cleanup.
    # File uploaders/buttons must not be assigned: store parsed uploads instead.
    names = {
        "analysis_mode", "resume_text", "job_description", "supplementary_note",
        "preferred_resume_option", "library_section",
        "library_project_source", "library_project_chunk",
        "enable_ai_review",
    }
    prefixes = (
        "direct_", "analysis_resume_", "interview_answer_",
    )
    for key in list(st.session_state):
        if "_files_" in key or key.endswith("_clear"):
            continue
        if key in names or key.startswith(prefixes):
            st.session_state[key] = st.session_state[key]


def uploaded_identity(files):
    return tuple((file.name, hashlib.sha256(file.getvalue()).hexdigest()) for file in files)


def accept_edited_document_text(text_key, upload_key):
    error = st.session_state.pop(f"document_input_error_{text_key}", None)
    if error:
        # Editing the retained text explicitly selects that text as the input.
        st.session_state[f"manual_override_{upload_key}"] = error["identity"]


def has_document_input_error(use_rag=False):
    keys = ["job_description"] if use_rag else ["resume_text", "job_description"]
    return any(st.session_state.get(f"document_input_error_{key}") for key in keys)


def render_document_input(label, text_key, upload_key, placeholder=""):
    uploaded = st.file_uploader(label, type=DOCUMENT_TYPES, key=upload_key)
    error_key = f"document_input_error_{text_key}"
    if uploaded is not None:
        identity = uploaded_identity([uploaded])
        identity_key = f"parsed_identity_{upload_key}"
        error = st.session_state.get(error_key)
        if identity in (st.session_state.get(identity_key), st.session_state.get(f"manual_override_{upload_key}")):
            st.session_state.pop(error_key, None)
        elif not error or error["identity"] != identity:
            try:
                parsed = parse_document(uploaded.name, uploaded.getvalue())
            except DocumentParseError as exc:
                st.session_state.pop(identity_key, None)
                st.session_state[error_key] = {"identity": identity, "message": str(exc)}
            else:
                st.session_state[text_key] = parsed.text
                st.session_state[identity_key] = identity
                st.session_state.pop(error_key, None)
                st.session_state.pop(f"manual_override_{upload_key}", None)
    else:
        st.session_state.pop(error_key, None)
        st.session_state.pop(f"manual_override_{upload_key}", None)
    text = st.text_area(
        "岗位 JD" if text_key == "job_description" else "简历内容",
        key=text_key, height=360, placeholder=placeholder,
        on_change=accept_edited_document_text, args=(text_key, upload_key),
    )
    error = st.session_state.get(error_key)
    if error:
        st.error(f"文件解析失败：{error['message']}。原有文本已保留，请移除失败文件或编辑文本后继续。")
    return text


def render_staged_documents(label, namespace, help_text=None):
    """Parse once and retain documents even when navigation removes the uploader."""
    generation = st.session_state.get(f"{namespace}_generation", 0)
    files = st.file_uploader(
        label, type=DOCUMENT_TYPES, accept_multiple_files=True,
        key=f"{namespace}_files_{generation}", help=help_text,
    )
    if files:
        identity = uploaded_identity(files)
        if st.session_state.get(f"{namespace}_identity") != identity:
            try:
                documents = [parse_document(file.name, file.getvalue()) for file in files]
            except DocumentParseError as exc:
                # Never silently use a previous upload when the replacement failed.
                st.session_state.pop(f"{namespace}_documents", None)
                st.session_state.pop(f"{namespace}_identity", None)
                st.session_state[f"{namespace}_error"] = str(exc)
                st.error(f"文件解析失败：{exc}")
            else:
                st.session_state.pop(f"{namespace}_error", None)
                st.session_state[f"{namespace}_documents"] = documents
                st.session_state[f"{namespace}_identity"] = identity
    documents = st.session_state.get(f"{namespace}_documents", [])
    if documents:
        st.caption("本次已暂存：" + "、".join(document.file_name for document in documents))
    if st.session_state.get(f"{namespace}_error"):
        st.error("本次上传解析失败，请重新上传有效文件，或清除本次上传后继续。")
    if documents or st.session_state.get(f"{namespace}_error"):
        if st.button("清除本次上传", key=f"{namespace}_clear"):
            clear_staged_documents(namespace)
            st.rerun()
    return documents


def clear_staged_documents(namespace):
    st.session_state.pop(f"{namespace}_error", None)
    st.session_state.pop(f"{namespace}_documents", None)
    st.session_state.pop(f"{namespace}_identity", None)
    st.session_state[f"{namespace}_generation"] = st.session_state.get(f"{namespace}_generation", 0) + 1
