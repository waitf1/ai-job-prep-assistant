from app.ui.styles import panel_heading
"""Display analysis conclusions first, with supporting detail on demand."""

import streamlit as st


def render_string_list(items: list[str], empty_message: str) -> None:
    if items:
        for item in items:
            st.markdown(f"- {item}")
    else:
        st.caption(empty_message)


def render_tool_calls(tool_calls) -> None:
    """Render inside the caller's expander without nesting expanders."""
    if not tool_calls:
        st.caption("本次没有可展示的工具调用记录。")
        return

    for index, call in enumerate(tool_calls, start=1):
        if index > 1:
            st.divider()
        status_text = "成功" if call.success else "失败"
        panel_heading(f"工具 {index}：{call.tool_name} | {status_text}")
        st.markdown(f"**输入摘要**：{call.input_summary or '无'}")
        st.markdown(f"**输出摘要**：{call.output_summary or '无'}")
        if call.error_message:
            st.error(call.error_message)


def _render_chunks(chunks) -> None:
    for index, chunk in enumerate(chunks, start=1):
        distance_text = f"{chunk.distance:.4f}" if chunk.distance is not None else "未知"
        st.markdown(
            f"**片段 {index} | 章节：{chunk.section_title} | 来源：{chunk.source} | "
            f"编号：{chunk.chunk_index} | 距离：{distance_text}**"
        )
        st.code(chunk.text)


def _render_retrieval(workflow_result, is_rag_mode, key_prefix, history_payload) -> None:
    if not is_rag_mode:
        st.info("普通分析模式下不执行资料库检索。")
        return

    if workflow_result.selected_resume:
        selected = workflow_result.selected_resume
        selection_mode = "系统自动选择" if selected.selection_mode == "automatic" else "用户手动指定"
        distance_text = f"{selected.distance:.4f}" if selected.distance is not None else "不适用"
        panel_heading("本次使用的完整简历")
        st.markdown(
            f"- 文件：`{selected.file_name}`\n"
            f"- 选择方式：{selection_mode}\n"
            f"- 自动匹配距离：{distance_text}"
        )

    if workflow_result.planner_decision:
        decision = workflow_result.planner_decision
        panel_heading("模型决策结果")
        st.markdown(f"- 是否检索：{'是' if decision.should_search else '否'}")
        st.markdown(f"- 决策说明：{decision.reason}")
        st.markdown(
            f"- 决策方式：{'模型通过工具调用决定检索' if decision.used_tool_call else '模型直接决定跳过检索'}"
        )

    if workflow_result.max_retrieval_distance is not None:
        raw_count = (
            history_payload["result"]["raw_retrieved_count"]
            if history_payload
            else len(workflow_result.raw_retrieved_chunks)
        )
        st.caption(
            f"系统自动选片：候选 {raw_count} 个，"
            f"实际采用 {len(workflow_result.retrieved_chunks)} 个，"
            f"内容排除 {workflow_result.content_filtered_chunk_count} 个，"
            f"距离过滤 {workflow_result.filtered_chunk_count} 个，"
            f"规则回退断层截断 {workflow_result.gap_truncated_chunk_count} 个，"
            f"AI 未采用 {workflow_result.ai_rerank_excluded_chunk_count} 个"
            f"（候选上限：{workflow_result.retrieval_candidate_limit}，"
            f"距离阈值：{workflow_result.max_retrieval_distance:.1f}）。"
        )
        if workflow_result.ai_rerank_reason:
            status = "失败回退" if workflow_result.ai_rerank_failed else "完成"
            st.caption(f"AI 相关性复核：{status}。{workflow_result.ai_rerank_reason}")
    else:
        st.caption(workflow_result.retrieval_message)

    if workflow_result.retrieval_query:
        st.text_area(
            "模型生成的检索查询",
            value=workflow_result.retrieval_query,
            key=f"{key_prefix}_retrieval_query",
            height=120,
            disabled=True,
        )

    if workflow_result.retrieved_chunks:
        panel_heading("本次采用的项目证据")
        _render_chunks(workflow_result.retrieved_chunks)

    if history_payload:
        st.caption("历史保存已采用的证据、检索统计和工具执行状态；未采用片段及原始工具输入输出不落盘。")

    # These groups already sit inside the retrieval expander. Plain headings
    # avoid nested expanders and keep the same details available on all versions.
    if workflow_result.content_filtered_chunks:
        st.divider()
        panel_heading(f"被排除的非正文内容（{workflow_result.content_filtered_chunk_count}）")
        for chunk in workflow_result.content_filtered_chunks:
            st.markdown(
                f"**类型：{chunk.content_type} | 章节：{chunk.section_title} | "
                f"来源：{chunk.source}**"
            )
            st.code(chunk.text)

    if workflow_result.distance_filtered_chunks:
        st.divider()
        panel_heading(f"被过滤的低相关片段（{workflow_result.filtered_chunk_count}）")
        st.caption("这些片段距离超过当前阈值，因此没有传入后续岗位分析。")
        _render_chunks(workflow_result.distance_filtered_chunks)

    if workflow_result.ai_rerank_failed and workflow_result.gap_truncated_chunks:
        st.divider()
        st.markdown(
            f"**规则回退时因相关性断层未采用的片段（{workflow_result.gap_truncated_chunk_count}）**"
        )
        st.caption("AI 重排序不可用时，系统按距离断层规则回退；这些片段因此未采用。")
        _render_chunks(workflow_result.gap_truncated_chunks)

    if workflow_result.ai_rerank_excluded_chunks:
        st.divider()
        panel_heading(f"AI 判断为不需要采用的片段（{workflow_result.ai_rerank_excluded_chunk_count}）")
        st.caption("这些片段已通过内容和距离规则，但 AI 判断其不能有效补充本次岗位分析。")
        _render_chunks(workflow_result.ai_rerank_excluded_chunks)

    if not workflow_result.retrieved_chunks:
        if workflow_result.retrieval_status == "skipped_by_model":
            st.info("模型判断本次可以跳过资料库检索。")
        elif workflow_result.retrieval_status == "no_relevant_results":
            st.warning(workflow_result.retrieval_message)
        elif workflow_result.retrieval_status == "no_results":
            st.info(workflow_result.retrieval_message)


def render_workflow_result(workflow_result, is_rag_mode, key_prefix="current", history_payload=None):
    st.subheader("岗位分析结果")

    panels = st.tabs(["能力匹配", "简历建议", "面试准备", "岗位要求", "项目证据与检索详情", "工具调用过程"])
    with panels[0]:
        panel_heading("当前匹配点")
        render_string_list(
            workflow_result.match_analysis.matched_points if workflow_result.match_analysis else [],
            "当前没有可展示的匹配点。",
        )
        if workflow_result.match_analysis:
            citations = workflow_result.match_analysis.citations
            if not citations:
                st.caption("本次未提供可逐字核对的原文引用，匹配结论仍需人工确认。")
            for index, citation in enumerate(citations):
                label = "简历原文" if citation["source"] == "resume" else "项目检索原文"
                with st.expander(f"匹配点 {citation['point_index'] + 1} · {label} · {'原文已核对' if citation['verified'] else '未通过核对'}"):
                    st.text(citation["quote"])
                    st.caption("原文核对仅验证文字存在，不代表模型的能力判断正确。")
                    if not citation["verified"]:
                        st.warning("引用未在本次输入中找到，请勿作为可靠证据使用。")
        panel_heading("当前缺口")
        render_string_list(
            workflow_result.match_analysis.gaps if workflow_result.match_analysis else [],
            "当前没有识别到明确缺口。",
        )
        panel_heading("证据说明")
        render_string_list(
            workflow_result.match_analysis.evidence_notes if workflow_result.match_analysis else [],
            "当前没有额外证据说明。",
        )

    with panels[1]:
        panel_heading("当前可以直接修改的表达")
        render_string_list(
            workflow_result.resume_advice.direct_edits if workflow_result.resume_advice else [],
            "当前没有生成可直接修改的表达。",
        )
        panel_heading("完成补充项目后可新增的表达")
        render_string_list(
            workflow_result.resume_advice.future_edits if workflow_result.resume_advice else [],
            "当前没有生成补充项目方向。",
        )

    with panels[2]:
        panel_heading("针对性面试问题")
        render_string_list(
            workflow_result.interview_prep.questions if workflow_result.interview_prep else [],
            "当前没有生成面试问题。",
        )
        panel_heading("短期补强建议")
        render_string_list(
            workflow_result.interview_prep.short_term_focus if workflow_result.interview_prep else [],
            "当前没有生成短期补强建议。",
        )

    with panels[3]:
        panel_heading("岗位职责")
        render_string_list(workflow_result.jd_analysis.responsibilities, "当前未提取到明确岗位职责。")
        panel_heading("必备技能")
        render_string_list(workflow_result.jd_analysis.required_skills, "当前未提取到明确必备技能。")
        panel_heading("加分项")
        render_string_list(workflow_result.jd_analysis.bonus_points, "当前未提取到明确加分项。")
        panel_heading("AI 关键词")
        render_string_list(workflow_result.jd_analysis.ai_keywords, "当前未提取到 AI 相关关键词。")
        panel_heading("面试关注点")
        render_string_list(workflow_result.jd_analysis.interview_focus, "当前未提取到面试关注点。")

    with panels[4]:
        _render_retrieval(workflow_result, is_rag_mode, key_prefix, history_payload)

    with panels[5]:
        st.caption(f"本次共记录 {len(workflow_result.tool_calls)} 次工具调用。")
        render_tool_calls(workflow_result.tool_calls)
