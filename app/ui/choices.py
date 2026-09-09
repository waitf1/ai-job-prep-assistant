"""Dropdown panels with togglable checkboxes and durable selections."""
import hashlib
from html import escape

import streamlit as st


def choice_key(key, value):
    return f"choice_{key}_{hashlib.sha256(str(value).encode()).hexdigest()[:12]}"


def _toggle(key, value, single):
    values = list(st.session_state.get(key, []))
    checked = st.session_state[choice_key(key, value)]
    if single:
        values = [value] if checked else []
    elif checked and value not in values:
        values.append(value)
    elif not checked and value in values:
        values.remove(value)
    st.session_state[key] = values


def checkbox_dropdown(label, options, key, *, default=(), single=False, format_func=str):
    st.session_state.setdefault(key, list(default))
    selected = [value for value in st.session_state[key] if value in options]
    if single:
        selected = selected[:1]
    st.session_state[key] = selected
    summary = "、".join(str(format_func(value)) for value in selected)
    hint = "单选" if single else "可多选"
    st.html(f'<div class="choice-label">{escape(label)} <span>{hint}</span></div>')
    button_text = (summary if len(summary) <= 55 else summary[:52] + "…") if selected else "点击选择…"
    with st.popover(button_text, width="stretch", key=f"dropdown_{key}",
                    help=f"点击选择{label}（{hint}）" + (f"；当前：{summary}" if summary else "")):
        st.caption(f"{label} · 点击勾选，再次点击取消")
        if not options:
            st.caption("暂无可选记录。")
        for value in options:
            widget_key = choice_key(key, value)
            st.session_state[widget_key] = value in selected
            st.checkbox(format_func(value), key=widget_key, on_change=_toggle, args=(key, value, single))
    return selected


def one_choice(label, options, key, *, default=None, format_func=str):
    values = checkbox_dropdown(label, options, key, default=[] if default is None else [default],
                               single=True, format_func=format_func)
    return values[0] if values else None


def context_switch():
    options = ["独立面试", "通过岗位分析结果进行面试"]
    saved = st.session_state.get("interview_context_choice", [options[0]])
    st.session_state["interview_context_toggle"] = next((v for v in saved if v in options), options[0])

    def sync():
        st.session_state["interview_context_choice"] = [st.session_state["interview_context_toggle"]]

    value = st.radio("面试上下文", options, key="interview_context_toggle", horizontal=True, on_change=sync)
    st.session_state["interview_context_choice"] = [value]
    return value
