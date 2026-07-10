import pandas as pd
import streamlit as st

from src.geo_fence import check_all_zones
from src.speed_anomaly import detect_by_vessel


def render_monthly_report_page(
    ais_query,
    restricted_zones,
    calc_monthly_vessel_rows,
    build_monthly_report_text,
    cached_report_docx_bytes,
    cached_report_pdf_bytes,
):
    st.markdown("**VTS 月度 AIS 活动报告生成**")

    month_options = sorted(
        pd.to_datetime(ais_query.df["time"]).dt.strftime("%Y-%m").unique().tolist()
    )
    if not month_options:
        st.warning("当前 AIS 数据中没有可生成报告的月份。")
    else:
        col_rep_1, col_rep_2, col_rep_3, col_rep_4 = st.columns([1, 1, 1, 1])
        with col_rep_1:
            default_month_idx = len(month_options) - 1
            month_label = st.selectbox(
                "报告月份",
                options=month_options,
                index=default_month_idx,
                key="monthly_report_month",
            )
        with col_rep_2:
            report_top_n = st.slider(
                "排行 Top N",
                min_value=5,
                max_value=20,
                value=10,
                step=5,
                key="monthly_report_top_n",
            )
        with col_rep_3:
            include_report_anomaly = st.checkbox(
                "包含航速异常",
                value=True,
                key="monthly_report_anomaly",
            )
        with col_rep_4:
            include_report_fence = st.checkbox(
                "包含围栏检测",
                value=True,
                key="monthly_report_fence",
            )

        anomaly_report_threshold = 2.5
        selected_report_zones = []
        col_rep_opts_1, col_rep_opts_2 = st.columns([1, 2])
        with col_rep_opts_1:
            if include_report_anomaly:
                anomaly_report_threshold = st.slider(
                    "报告异常 Z-Score 阈值",
                    min_value=1.5,
                    max_value=4.0,
                    value=2.5,
                    step=0.1,
                    key="monthly_report_anomaly_threshold",
                )
        with col_rep_opts_2:
            if include_report_fence:
                report_zone_names = [z["name"] for z in restricted_zones]
                selected_report_zone_names = st.multiselect(
                    "报告围栏区域",
                    options=report_zone_names,
                    default=report_zone_names,
                    key="monthly_report_zones",
                )
                selected_report_zones = [
                    z for z in restricted_zones
                    if z["name"] in selected_report_zone_names
                ]

        if "monthly_report_payload" not in st.session_state:
            st.session_state.monthly_report_payload = None

        if st.button("📄 生成月度报告", type="primary", key="generate_monthly_report"):
            year = int(month_label[:4])
            month = int(month_label[5:7])
            month_start = pd.Timestamp(f"{month_label}-01")
            month_end = month_start + pd.DateOffset(months=1)
            month_df = ais_query.df[
                (ais_query.df["time"] >= month_start)
                & (ais_query.df["time"] < month_end)
            ].copy()

            if len(month_df) == 0:
                st.warning(f"{month_label} 没有 AIS 轨迹数据。")
                st.session_state.monthly_report_payload = None
            else:
                with st.spinner("正在汇总月度 AIS 数据..."):
                    monthly_vessels = _calc_monthly_vessel_rows(month_df, ais_query)
                    report_anomalies = None
                    report_violations = None

                    if include_report_anomaly:
                        report_anomalies = detect_by_vessel(
                            month_df,
                            threshold=anomaly_report_threshold,
                            min_n=5,
                        )

                    if include_report_fence:
                        report_violations = check_all_zones(month_df, selected_report_zones)

                    report_text = build_monthly_report_text(
                        year=year,
                        month=month,
                        month_df=month_df,
                        monthly_vessels=monthly_vessels,
                        anomalies=report_anomalies,
                        violations=report_violations,
                        top_n=report_top_n,
                    )

                    st.session_state.monthly_report_payload = {
                        "month_label": month_label,
                        "month_df": month_df,
                        "monthly_vessels": monthly_vessels,
                        "anomalies": report_anomalies,
                        "violations": report_violations,
                        "text": report_text,
                        "top_n": report_top_n,
                    }

        payload = st.session_state.monthly_report_payload
        if payload is not None:
            month_df = payload["month_df"]
            monthly_vessels = payload["monthly_vessels"]
            report_anomalies = payload["anomalies"]
            report_violations = payload["violations"]
            report_text = payload["text"]
            top_n = payload["top_n"]

            st.markdown(f"### {payload['month_label']} 报告预览")
            rep_stat_cols = st.columns(4)
            with rep_stat_cols[0]:
                st.metric("活跃船只", month_df["vessel_id"].nunique())
            with rep_stat_cols[1]:
                st.metric("轨迹点数", f"{len(month_df):,}")
            with rep_stat_cols[2]:
                stop_ratio = (month_df["sog"] < 0.5).sum() / len(month_df) * 100
                st.metric("停泊点占比", f"{stop_ratio:.1f}%")
            with rep_stat_cols[3]:
                st.metric("最高航速", f"{float(month_df['sog'].max()):.1f} kn")

            if len(monthly_vessels) > 0:
                st.markdown("**月度航程 Top 船只**")
                preview_rank = (
                    monthly_vessels.sort_values("估算航程(nm)", ascending=False)
                    .head(top_n)
                    .reset_index(drop=True)
                )
                preview_rank.insert(0, "排名", range(1, len(preview_rank) + 1))
                st.dataframe(preview_rank, use_container_width=True, hide_index=True)

            col_report_a, col_report_b = st.columns(2)
            with col_report_a:
                if report_anomalies is None:
                    st.info("本次报告未启用航速异常检测。")
                elif len(report_anomalies) == 0:
                    st.success("未发现航速异常。")
                else:
                    st.warning(
                        f"检测到 {len(report_anomalies)} 条航速异常，"
                        f"涉及 {report_anomalies['vessel_id'].nunique()} 艘船。"
                    )
            with col_report_b:
                if report_violations is None:
                    st.info("本次报告未启用围栏检测。")
                elif len(report_violations) == 0:
                    st.success("未发现围栏违例。")
                else:
                    st.warning(
                        f"检测到 {len(report_violations)} 条围栏违例，"
                        f"涉及 {report_violations['vessel_id'].nunique()} 艘船。"
                    )

            st.markdown("**Markdown 报告正文**")
            st.text_area(
                "报告内容",
                value=report_text,
                height=420,
                key="monthly_report_text_preview",
            )
            st.download_button(
                "下载 Markdown 报告",
                data=report_text.encode("utf-8-sig"),
                file_name=f"vts_monthly_report_{payload['month_label']}.md",
                mime="text/markdown",
                key="download_monthly_report_md",
                on_click="ignore",
            )
            col_export_docx, col_export_pdf = st.columns(2)
            with col_export_docx:
                try:
                    docx_bytes = _cached_report_docx_bytes(report_text)
                    st.download_button(
                        "下载 Word 报告",
                        data=docx_bytes,
                        file_name=f"vts_monthly_report_{payload['month_label']}.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key="download_monthly_report_docx",
                        on_click="ignore",
                    )
                except RuntimeError as e:
                    st.error(str(e))
            with col_export_pdf:
                try:
                    pdf_bytes = _cached_report_pdf_bytes(report_text)
                    st.download_button(
                        "下载 PDF 报告",
                        data=pdf_bytes,
                        file_name=f"vts_monthly_report_{payload['month_label']}.pdf",
                        mime="application/pdf",
                        key="download_monthly_report_pdf",
                        on_click="ignore",
                    )
                except RuntimeError as e:
                    st.error(str(e))
