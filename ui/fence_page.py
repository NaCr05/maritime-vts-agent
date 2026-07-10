import traceback

import pandas as pd
import pydeck as pdk
import streamlit as st

from src.geo_fence import check_all_zones, get_violation_trajectory_segments, summarize_violations


def render_fence_page(ais_query, registry, restricted_zones, safe_deck):
    st.markdown("**🛡️ 地理围栏检测 — 自动识别进入禁航区域的船只**")

    # 初始化 session state
    if "fence_violations" not in st.session_state:
        st.session_state.fence_violations = None
    if "fence_violation_segments" not in st.session_state:
        st.session_state.fence_violation_segments = None

    # ① 选择船只
    st.markdown("**① 选择船只**")
    vessel_labels_fence = [
        f"{m['vessel_id']} ({m['n_points']} 点, "
        f"{m['time_start'][:10]} ~ {m['time_end'][:10]})"
        for m in registry
    ]
    vessel_id_map_fence = {
        label: m["vessel_id"] for label, m in zip(vessel_labels_fence, registry)
    }
    selected_fence_labels = st.multiselect(
        "选择要检测的船只（可多选）",
        options=vessel_labels_fence,
        default=vessel_labels_fence[: min(5, len(vessel_labels_fence))],
        key="fence_vessel_select",
    )
    fence_vessel_ids = [vessel_id_map_fence[l] for l in selected_fence_labels]

    # ② 选择围栏区域
    st.markdown("**② 选择 / 配置禁航区域**")
    col_zone_sel, col_zone_add = st.columns([2, 1])
    with col_zone_sel:
        zone_options = [z["name"] for z in restricted_zones]
        selected_zone_names = st.multiselect(
            "勾选预定义禁航区域",
            options=zone_options,
            default=[],          # 默认全不选，由用户主动勾选
            key="fence_zone_select",
        )
    with col_zone_add:
        st.markdown("**或添加自定义圆形区域**")
        with st.expander("➕ 添加自定义区域"):
            c_name = st.text_input("区域名称", key="fence_custom_name", placeholder="例如：临时演练区")
            c_lat = st.number_input("中心纬度", key="fence_custom_lat", min_value=0.0, max_value=90.0, value=30.5, format="%.4f")
            c_lon = st.number_input("中心经度", key="fence_custom_lon", min_value=0.0, max_value=180.0, value=122.0, format="%.4f")
            c_r = st.number_input("半径（海里）", key="fence_custom_r", min_value=0.5, max_value=50.0, value=5.0, step=0.5)
            if st.button("确认添加", key="fence_add_btn"):
                if c_name and c_name not in [z["name"] for z in restricted_zones]:
                    st.session_state.custom_zones = getattr(st.session_state, "custom_zones", [])
                    st.session_state.custom_zones.append({
                        "name": c_name,
                        "type": "circle",
                        "lat": c_lat,
                        "lon": c_lon,
                        "radius_nm": c_r,
                    })
                    st.success(f"已添加区域：{c_name}（{c_lat}°N, {c_lon}°E，半径 {c_r} 海里）")
                    st.rerun()
                elif c_name in [z["name"] for z in restricted_zones]:
                    st.warning("名称已存在，请换一个名称")

    # 构建最终检测区域列表
    all_zones = []
    for z in restricted_zones:
        if z["name"] in selected_zone_names:
            all_zones.append(z)
    custom_zones = getattr(st.session_state, "custom_zones", [])
    all_zones.extend(custom_zones)

    # 一键以「船只实际活动范围」创建测试区域
    if len(fence_vessel_ids) > 0:
        with st.expander("🎯 一键用选中船只的活动中心建测试区域（必定触发违例）", expanded=False):
            col_info = st.columns([1, 3])
            with col_info[0]:
                test_zone_radius = st.number_input(
                    "测试区域半径（海里）",
                    min_value=1.0, max_value=50.0,
                    value=3.0, step=0.5,
                    key="fence_test_radius",
                )
            with col_info[1]:
                st.write("")
                if st.button("✈️ 建测试区域", key="fence_create_test_zone"):
                    test_traj = ais_query.get_multi_trajectories(fence_vessel_ids)
                    test_lat = float(test_traj["lat"].mean())
                    test_lon = float(test_traj["lon"].mean())
                    existing_count = len(getattr(st.session_state, "custom_zones", []))
                    test_name = f"测试区域_{existing_count + 1}"
                    st.session_state.custom_zones = getattr(st.session_state, "custom_zones", [])
                    st.session_state.custom_zones.append({
                        "name": test_name,
                        "type": "circle",
                        "lat": test_lat,
                        "lon": test_lon,
                        "radius_nm": test_zone_radius,
                    })
                    st.success(f"已添加「{test_name}」（{test_lat:.4f}°N, {test_lon:.4f}°E，半径 {test_zone_radius} 海里）")
                    st.rerun()

    # 显示当前已选区域（含自定义区域的删除入口）
    custom_zones = getattr(st.session_state, "custom_zones", [])
    if all_zones:
        parts = []
        for i, z in enumerate(all_zones):
            is_custom = i >= len(all_zones) - len(custom_zones)
            tag = f"🔵 {z['name']}" if is_custom else f"🔷 {z['name']}"
            parts.append(tag)
        if custom_zones:
            parts.append(f"🗑️ [清除全部自定义区域]")
        st.caption("✅ 已选 " + " | ".join(parts))
    else:
        st.caption("ℹ️ 暂未选择任何禁航区域，可直接点击上方按钮开始检测")

    # 清除全部自定义区域的响应（通过 session_state 标志触发）
    if "fence_clear_custom" not in st.session_state:
        st.session_state.fence_clear_custom = False
    if st.session_state.fence_clear_custom:
        st.session_state.custom_zones = []
        st.session_state.fence_clear_custom = False
        st.rerun()

    if custom_zones:
        st.caption("**已创建的自定义区域（可删除后重建）：**")
        cols_del = st.columns(len(custom_zones))
        for i, (col, zone) in enumerate(zip(cols_del, custom_zones)):
            with col:
                st.write(f"🔵 {zone['name']}（{zone['lat']:.4f}°N, {zone['lon']:.4f}°E, {zone['radius_nm']}海里）")
                if st.button("🗑️ 删除", key=f"fence_del_zone_{i}"):
                    st.session_state.custom_zones.pop(i)
                    st.rerun()

    # 检测按钮（始终显示，不依赖是否选择了区域）
    col_display, col_btn = st.columns([4, 1])
    with col_btn:
        run_check = st.button("🔍 检测违例", type="primary", use_container_width=True)

    if run_check:
        if not fence_vessel_ids:
            st.warning("请先选择至少一艘船。")
            st.session_state.fence_violations = None
        else:
            with st.spinner("正在检测禁航区违例..."):
                try:
                    fence_traj = ais_query.get_multi_trajectories(fence_vessel_ids)
                    violations = check_all_zones(fence_traj, all_zones)
                    st.session_state.fence_violations = violations
                    if len(violations) > 0:
                        segs = get_violation_trajectory_segments(fence_traj, violations)
                        st.session_state.fence_violation_segments = segs
                    else:
                        st.session_state.fence_violation_segments = None
                except Exception as e:
                    st.error(f"检测失败：{e}")
                    st.session_state.fence_violations = None

                violations = st.session_state.fence_violations

                if violations is None or len(violations) == 0:
                    st.success("✅ 未发现进入禁航区域的船只。")
                else:
                    st.warning(f"⚠️ 检测到 **{violations['vessel_id'].nunique()}** 艘船进入禁航区，共 **{len(violations)}** 条违例记录。")

                    # ③ 统计卡片
                    top_vessels = (
                        violations.groupby("vessel_id")["n_entries"]
                        .sum().sort_values(ascending=False).head(3)
                    )
                    col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)
                    with col_stat1:
                        st.metric("违例船只", violations["vessel_id"].nunique())
                    with col_stat2:
                        st.metric("违例记录", len(violations))
                    with col_stat3:
                        top_v = top_vessels.index[0] if len(top_vessels) > 0 else "-"
                        st.metric("最频繁违例船只", f"船 {int(top_v)}" if top_v != "-" else "-")
                    with col_stat4:
                        top_z = violations.groupby("zone_name")["vessel_id"].nunique().idxmax()
                        st.metric("最多船进入的区域", top_z)

                    # ④ 违例表格
                    st.markdown("**④ 违例明细**")
                    disp = violations[[
                        "vessel_id", "zone_name", "zone_type",
                        "first_entry", "duration_h", "n_entries", "n_points"
                    ]].copy()
                    disp["vessel_id"] = disp["vessel_id"].apply(lambda x: f"船 {int(x)}")
                    disp.columns = ["船只", "区域", "类型", "首次进入", "滞留时长(h)", "进入次数", "轨迹点数"]
                    st.dataframe(disp, use_container_width=True, hide_index=True)

                    # ⑤ 违例轨迹地图
                    if st.session_state.fence_violation_segments:
                        st.markdown("**⑤ 违例轨迹地图（红色高亮）**")
                        segs = st.session_state.fence_violation_segments

                        # 基础地图：用正常轨迹
                        base_traj = ais_query.get_multi_trajectories(fence_vessel_ids)
                        base_lat = float(base_traj["lat"].mean())
                        base_lon = float(base_traj["lon"].mean())

                        base_path_data = []
                        for vid in fence_vessel_ids:
                            vdf = base_traj[base_traj["vessel_id"] == vid].sort_values("time")
                            if len(vdf) < 2:
                                continue
                            base_path_data.append({
                                "path": [[float(r.lon), float(r.lat)] for _, r in vdf.iterrows()],
                                "color": [120, 120, 120, 120],
                                "vessel_id": int(vid),
                                "width": 200,
                                "label": f"船 {int(vid)} 轨迹",
                            })

                        # 违例高亮层
                        violation_path_data = []
                        for vid, info in segs.items():
                            for path, zone_name in zip(info["paths"], info["zone_names"]):
                                if len(path) < 2:
                                    continue
                                violation_path_data.append({
                                    "path": path,
                                    "color": [255, 30, 30, 220],
                                    "vessel_id": int(vid),
                                    "width": 600,
                                    "label": f"船 {int(vid)} 进入 {zone_name}",
                                })

                        # 违例进入点
                        violation_scatter = []
                        for _, row in violations.iterrows():
                            violation_scatter.append({
                                "position": [float(row["entry_lon"]), float(row["entry_lat"])],
                                "color": [255, 0, 0],
                                "radius": 3000,
                                "label": f"船 {int(row['vessel_id'])} → {row['zone_name']}",
                            })

                        layers = []
                        if base_path_data:
                            layers.append(pdk.Layer(
                                "PathLayer", data=base_path_data,
                                get_width="width", get_color="color",
                                pickable=True,
                            ))
                        if violation_path_data:
                            layers.append(pdk.Layer(
                                "PathLayer", data=violation_path_data,
                                get_width="width", get_color="color",
                                pickable=True,
                            ))
                        if violation_scatter:
                            layers.append(pdk.Layer(
                                "ScatterplotLayer", data=violation_scatter,
                                get_position="position",
                                get_fill_color="color",
                                get_radius="radius",
                                pickable=True,
                            ))

                        deck_fence = safe_deck(
                            layers=layers,
                            initial_view_state=pdk.ViewState(
                                latitude=base_lat,
                                longitude=base_lon,
                                zoom=9,
                                pitch=35,
                            ),
                            height=500,
                            tooltip={
                                "html": "<b>{label}</b>",
                                "style": {"color": "white", "font-size": "12px"},
                            },
                        )
                        st.pydeck_chart(deck_fence, use_container_width=True)

                        # 图例
                        col_leg1, col_leg2, col_leg3 = st.columns(3)
                        with col_leg1:
                            st.markdown("🟦 **灰色**：正常轨迹")
                        with col_leg2:
                            st.markdown("🔴 **红色粗线**：违例段")
                        with col_leg3:
                            st.markdown("⚫ **红点**：首次进入位置")

                    # 摘要文本
                    st.markdown("**📋 检测摘要**")
                    summary_text = summarize_violations(violations)
                    st.info(summary_text)
