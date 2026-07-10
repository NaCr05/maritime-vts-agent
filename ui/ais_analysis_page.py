import streamlit as st


AIS_ANALYSIS_TABS = [
    "🤒 航速异常检测",
    "🗺️ 轨迹地图可视化",
    "单船轨迹回放",
    "🧭 航次识别",
    "多船联合分析",
    "⚓ 停泊点分布",
    "⚓ 锚地聚类",
    "🏆 航行排行榜",
    "📄 月度报告",
    "🛡️ 地理围栏",
    "自然语言查询",
]


def render_ais_analysis_nav() -> str:
    """Render the AIS analysis sub-navigation and return the active section."""
    return st.radio(
        "AIS 分析功能",
        AIS_ANALYSIS_TABS,
        horizontal=True,
        label_visibility="collapsed",
        key="ais_analysis_nav",
    )
