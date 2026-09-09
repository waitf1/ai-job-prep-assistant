from app.ui.styles import panel_heading
import streamlit as st


def render_interview_summary(summary):
    st.caption("复盘基于各轮限长摘录生成；超过 50 轮时均匀抽样。完整回答可在逐轮记录中查看。")
    panels = st.tabs(["整体评价", "强项", "薄弱点", "回答结构", "练习建议"])
    with panels[0]:
        st.write(summary.overall_summary or "已完成面试复盘。")
    for panel, (title, values) in zip(panels[1:], (
        ("强项", summary.strengths), ("薄弱点", summary.weaknesses),
        ("推荐回答结构", summary.answer_structure_advice), ("后续练习建议", summary.practice_plan),
    )):
        with panel:
            panel_heading(f"{title}")
            for value in values:
                st.write(value)
            if not values:
                st.caption("未提供此项内容。")


def render_interview_history(rounds):
    labels = {"theory": "岗位技术理论", "project": "简历项目经历", "question_bank": "自选题库"}
    if not rounds:
        st.caption("尚无已完成的问答记录。")
        return
    panels = st.tabs([f"第 {i} 轮完整记录" for i in range(1, len(rounds) + 1)])
    for panel, item in zip(panels, rounds):
        with panel:
            panel_heading("面试问题")
            st.write(item.question)
            st.caption(f"题目来源：{labels.get(item.question_source, item.question_source)}")
            panel_heading("你的原始回答")
            st.code(item.answer)
            st.caption(f"评分：{item.feedback.score} / 100")
            for title, values in (
                ("表现亮点", item.feedback.strengths),
                ("优先改进点", item.feedback.improvements),
                ("建议回答结构", item.feedback.answer_structure),
            ):
                panel_heading(f"{title}")
                if not values:
                    st.caption("本轮未提供此项内容。")
                for value in values:
                    st.write(value)
            panel_heading("面试官反馈")
            st.write(item.feedback.overall_feedback or "本轮未提供整体反馈。")
