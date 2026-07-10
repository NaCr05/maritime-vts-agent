import streamlit as st


def render_rag_page(rag_engine, top_k, registry, render_sources):
    st.subheader("海事知识库问答")
    st.write("你可以追问任何之前提过的问题，系统会结合上下文一起检索并回答。")

    # 引导用户区分 Tab 用途，避免在 Tab 1 问具体船数据
    st.info(
        "💡 **本 Tab 用于查询 VTS / AIS 概念、规则、行业知识（基于知识库检索 + LLM 生成）。**\n\n"
        "**查具体船只的数据（如\"船 18330 的统计摘要\"）请切到右边的 "
        "\"AIS 轨迹分析 → 自然语言查询\"**"
    )

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("请输入你的问题"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            if rag_engine.has_llm():
                with st.spinner("正在检索知识库并生成回答..."):
                    # 流式调用：把生成器塞给 st.write_stream
                    result_holder: dict = {}
                    generator = rag_engine.stream_ask(
                        prompt,
                        top_k=top_k,
                        chat_history=st.session_state.messages[:-1],
                        vessel_ids=[m["vessel_id"] for m in registry],
                    )

                    # 包装生成器以便拿到最终结果（含 sources）
                    def gen_wrapper():
                        try:
                            while True:
                                chunk = next(generator)
                                yield chunk
                        except StopIteration as e:
                            result_holder["result"] = e.value or {}

                    output_text = st.write_stream(gen_wrapper())
                    result = result_holder.get(
                        "result", {"sources": [], "retrieval_mode": "general"}
                    )
            else:
                with st.spinner("正在检索知识库..."):
                    result = rag_engine.ask(
                        prompt,
                        top_k=top_k,
                        chat_history=st.session_state.messages[:-1],
                        vessel_ids=[m["vessel_id"] for m in registry],
                    )
                st.markdown(result["answer"])
                output_text = result["answer"]

            render_sources(
                result.get("sources", []),
                result.get("retrieval_mode", "rag"),
            )

        st.session_state.messages.append(
            {"role": "assistant", "content": output_text}
        )

    if st.session_state.messages and st.button("清空对话", type="secondary"):
        st.session_state.messages = []
        st.rerun()
