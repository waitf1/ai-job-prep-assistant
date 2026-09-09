from datetime import datetime, timedelta, timezone
import html

import streamlit as st

from app.storage.history_snapshots import restore_analysis, restore_interview
from app.ui.interview_history import render_interview_history, render_interview_summary
from app.ui.choices import one_choice


def record_preview(record):
    try:
        if record.kind == "analysis":
            body = record.payload["result"]
            match = body.get("match_analysis") or {}
            return "岗位：" + record.payload["job_description"][:350] + "\n匹配点：" + "；".join(match.get("matched_points", []))[:250]
        return f"共 {len(record.payload['rounds'])} 轮。" + record.payload["summary"].get("overall_summary", "")[:500]
    except (KeyError, TypeError, AttributeError):
        return "记录详情暂不可用，点击查看详情检查。"


def close_history_dialog():
    st.session_state.pop("history_delete_target", None)


@st.dialog("确认删除历史记录", on_dismiss=close_history_dialog)
def confirm_delete_history(store_factory, record):
    st.warning(f"确定删除「{record.title}」？此操作不可撤销。")
    st.caption("不会删除简历和项目资料；删除分析只解除已保存复盘的关联。")
    if st.button("确认删除", type="primary", key="history_delete_confirm_action"):
        try:
            store_factory().delete(record.record_id)
        except Exception:
            st.error("删除失败，请稍后重试。")
        else:
            close_history_dialog()
            st.session_state.pop("history_detail_id", None)
            st.rerun()
    if st.button("取消", key="history_delete_cancel"):
        close_history_dialog()
        st.rerun()


def render_history_panel(store_factory, render_analysis, on_prepare):
    st.caption("查看主动保存的岗位分析与面试复盘。")
    detail_id = st.session_state.get("history_detail_id")
    if detail_id:
        if st.button("返回记录列表"):
            st.session_state.pop("history_detail_id", None)
            st.rerun()
        try:
            record = store_factory().get(detail_id)
        except Exception:
            st.error("记录不存在或暂时无法读取，请返回列表重新选择。")
            return
        st.subheader(record.title)
        st.caption(f"创建于 {record.created_at[:19].replace('T', ' ')} UTC")
        try:
            if record.kind == "analysis":
                result = restore_analysis(record.payload)
                with st.popover("查看原始岗位 JD"):
                    st.text(record.payload["job_description"])
                render_analysis(result, record.payload["use_rag"], key_prefix=f"history_{detail_id}", history_payload=record.payload)
                if st.button("去模拟面试", key=f"history_prepare_{detail_id}", type="primary"):
                    on_prepare(record.record_id)
            else:
                rounds, summary = restore_interview(record.payload)
                st.caption(f"共 {len(rounds)} 轮；关联分析：{record.analysis_id or '无'}")
                summary_tab, rounds_tab = st.tabs(["面试复盘", "逐轮记录"])
                with summary_tab:
                    render_interview_summary(summary)
                with rounds_tab:
                    render_interview_history(rounds)
        except (KeyError, TypeError, ValueError, AttributeError):
            st.error("该记录内容损坏或版本不兼容，无法显示详情；其他记录仍可使用。")
        if st.button("删除此记录", key=f"history_delete_{detail_id}"):
            st.session_state["history_delete_target"] = detail_id
        if st.session_state.get("history_delete_target") == detail_id:
            confirm_delete_history(store_factory, record)
        return
    left, right = st.columns(2)
    with left:
        kind = one_choice("记录类型", ["全部", "岗位分析", "面试复盘"], "history_kind_choice", default="全部") or "全部"
    with right:
        days = one_choice("创建时间", [0, 7, 30, 90], "history_days_choice", default=0,
                          format_func=lambda value: "全部时间" if value == 0 else f"最近 {value} 天") or 0
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat() if days else None
    try:
        records = store_factory().list_records(kind={"全部": None, "岗位分析": "analysis", "面试复盘": "interview"}[kind], since=since)
    except Exception:
        st.error("历史记录暂时无法读取。请检查数据库是否被占用或损坏；当前分析和面试仍可使用。")
        return
    if not records:
        st.info("此范围内还没有保存的记录。")
        return
    st.caption(f"共 {len(records)} 条记录 · 悬停摘要查看预览")
    st.html("""<style>
    .history-preview {position:relative; padding:8px 0; cursor:help;}
    .history-preview .history-tip {display:none;position:absolute;left:0;top:100%;z-index:1000;
        background:#fff;color:#263244;border:1px solid #e1e4ee;border-radius:8px;padding:14px;
        width:min(520px,80vw);white-space:pre-wrap;box-shadow:0 6px 20px #0005;}
    .history-preview:hover .history-tip,.history-preview:focus .history-tip {display:block;}
    </style>""")
    for record in records:
        with st.container(border=True):
            body, action = st.columns([5, 1], vertical_alignment="center")
            with body:
                label = "岗位分析" if record.kind == "analysis" else "面试复盘"
                preview = record_preview(record)
                st.caption(f"{label} · {record.created_at[:19].replace('T', ' ')} UTC")
                st.html(f'<div class="history-preview" tabindex="0"><strong class="record-title">{html.escape(record.title)}</strong>'
                        f'<div class="record-summary">{html.escape(preview[:100])}</div><span class="history-tip" role="tooltip">{html.escape(preview)}</span></div>')
            with action:
                if st.button("查看详情", key=f"history_view_{record.record_id}"):
                    st.session_state["history_detail_id"] = record.record_id
                    st.rerun()
