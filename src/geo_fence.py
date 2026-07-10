"""
地理围栏检测模块

支持矩形围栏和圆形围栏两种区域类型：
- 矩形：lat_min/max + lon_min/max 范围判定
- 圆形：以 lat/lon 为圆心、半径（海里）为半径的 Haversine 距离判定

用法示例：
    from src.geo_fence import check_rectangular_zones, check_circular_zones
    violations = check_rectangular_zones(traj_df, zones)
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional


# ---- 工具函数 ----

def _in_rect(lat: float, lon: float, zone: Dict[str, Any]) -> bool:
    """判断点是否在矩形区域内。"""
    return (
        zone["lat_min"] <= lat <= zone["lat_max"]
        and zone["lon_min"] <= lon <= zone["lon_max"]
    )


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两点间 Haversine 距离，单位：海里。"""
    R = 180 * 60 / np.pi
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
    return float(2 * np.arcsin(np.sqrt(a)) * R)


def _in_circle(lat: float, lon: float, zone: Dict[str, Any]) -> bool:
    """判断点是否在圆形区域内（半径以 nautical mile 为单位）。"""
    d = haversine_nm(lat, lon, zone["lat"], zone["lon"])
    return d <= zone["radius_nm"]


def _extract_violation_segments(
    traj: pd.DataFrame,
    zone: Dict[str, Any],
    zone_type: str,
) -> List[Dict[str, Any]]:
    """从一条轨迹中提取所有进入该区域的片段，返回每个片段的信息。"""
    lat_col = traj["lat"].values
    lon_col = traj["lon"].values
    time_col = traj["time"].values
    n = len(traj)

    if n == 0:
        return []

    # 构建"是否在区域内"的布尔数组
    in_zone = np.array([
        _in_rect(lat_col[i], lon_col[i], zone)
        if zone_type == "rect"
        else _in_circle(lat_col[i], lon_col[i], zone)
        for i in range(n)
    ])

    # 找状态切换点（0→1 = 进入，1→0 = 离开）
    transitions = np.diff(in_zone.astype(int), prepend=0, append=0)
    enter_idx = np.where(transitions == 1)[0]   # 进入的起始索引
    exit_idx = np.where(transitions == -1)[0]   # 离开的起始索引

    # 收尾：如果最后仍在区域内，exit_idx 补上末尾
    if len(enter_idx) > len(exit_idx):
        exit_idx = np.append(exit_idx, n)

    segments = []
    for s, e in zip(enter_idx, exit_idx):
        seg_traj = traj.iloc[s:e]
        if len(seg_traj) == 0:
            continue
        first_time = seg_traj["time"].iloc[0]
        last_time = seg_traj["time"].iloc[-1]
        duration_h = (pd.Timestamp(last_time) - pd.Timestamp(first_time)).total_seconds() / 3600
        segments.append({
            "first_entry": str(first_time),
            "last_exit": str(last_time),
            "duration_h": round(duration_h, 2),
            "n_points": len(seg_traj),
            "entry_lat": float(seg_traj["lat"].iloc[0]),
            "entry_lon": float(seg_traj["lon"].iloc[0]),
            "exit_lat": float(seg_traj["lat"].iloc[-1]),
            "exit_lon": float(seg_traj["lon"].iloc[-1]),
        })

    return segments


# ---- 主检测函数 ----

def check_rectangular_zones(
    traj_df: pd.DataFrame,
    zones: List[Dict[str, Any]],
) -> pd.DataFrame:
    """
    检测所有轨迹点是否落入矩形围栏区域。

    Args:
        traj_df: AIS 轨迹 DataFrame，必须包含 vessel_id, time, lat, lon 列
        zones: 矩形区域列表，每项必须包含 name, lat_min, lat_max, lon_min, lon_max

    Returns:
        DataFrame，每行代表一条船在一个区域中的一次违例记录。
        列：vessel_id, zone_name, zone_type, first_entry, last_exit,
            duration_h, n_entries, n_points
    """
    rows: List[Dict[str, Any]] = []

    for vid, vdf in traj_df.groupby("vessel_id", sort=False):
        vdf = vdf.sort_values("time")
        for zone in zones:
            segments = _extract_violation_segments(vdf, zone, "rect")
            if not segments:
                continue
            first_seg = segments[0]
            last_seg = segments[-1]
            rows.append({
                "vessel_id": int(vid),
                "zone_name": zone["name"],
                "zone_type": "矩形",
                "first_entry": first_seg["first_entry"],
                "last_exit": last_seg["last_exit"],
                "duration_h": round(sum(s["duration_h"] for s in segments), 2),
                "n_entries": len(segments),
                "n_points": sum(s["n_points"] for s in segments),
                # 第一个进入点的坐标（供地图展示用）
                "entry_lat": first_seg["entry_lat"],
                "entry_lon": first_seg["entry_lon"],
            })

    if not rows:
        return _empty_violation_df()

    df = pd.DataFrame(rows)
    return df.sort_values(["vessel_id", "first_entry"]).reset_index(drop=True)


def check_circular_zones(
    traj_df: pd.DataFrame,
    zones: List[Dict[str, Any]],
) -> pd.DataFrame:
    """
    检测所有轨迹点是否落入圆形围栏区域。

    Args:
        traj_df: AIS 轨迹 DataFrame，必须包含 vessel_id, time, lat, lon 列
        zones: 圆形区域列表，每项必须包含 name, lat, lon, radius_nm

    Returns:
        同 check_rectangular_zones，zone_type 为"圆形"
    """
    rows: List[Dict[str, Any]] = []

    for vid, vdf in traj_df.groupby("vessel_id", sort=False):
        vdf = vdf.sort_values("time")
        for zone in zones:
            segments = _extract_violation_segments(vdf, zone, "circle")
            if not segments:
                continue
            first_seg = segments[0]
            last_seg = segments[-1]
            rows.append({
                "vessel_id": int(vid),
                "zone_name": zone["name"],
                "zone_type": "圆形",
                "first_entry": first_seg["first_entry"],
                "last_exit": last_seg["last_exit"],
                "duration_h": round(sum(s["duration_h"] for s in segments), 2),
                "n_entries": len(segments),
                "n_points": sum(s["n_points"] for s in segments),
                "entry_lat": first_seg["entry_lat"],
                "entry_lon": first_seg["entry_lon"],
            })

    if not rows:
        return _empty_violation_df()

    df = pd.DataFrame(rows)
    return df.sort_values(["vessel_id", "first_entry"]).reset_index(drop=True)


def check_all_zones(
    traj_df: pd.DataFrame,
    zones: List[Dict[str, Any]],
) -> pd.DataFrame:
    """
    同时检测矩形和圆形区域（自动根据 zone 中的字段判断类型）。

    Args:
        traj_df: AIS 轨迹 DataFrame
        zones: 混合区域列表，矩形包含 lat_min/max/lon_min/max，
               圆形包含 lat/lon/radius_nm

    Returns:
        合并后的违例 DataFrame
    """
    rect_zones = [z for z in zones if "lat_min" in z]
    circ_zones = [z for z in zones if "lat" in z and "radius_nm" in z]

    dfs = []
    if rect_zones:
        dfs.append(check_rectangular_zones(traj_df, rect_zones))
    if circ_zones:
        dfs.append(check_circular_zones(traj_df, circ_zones))

    if not dfs:
        return _empty_violation_df()

    combined = pd.concat(dfs, ignore_index=True)
    return combined.sort_values(["vessel_id", "first_entry"]).reset_index(drop=True)


def get_violation_trajectory_segments(
    traj_df: pd.DataFrame,
    violation_df: pd.DataFrame,
) -> Dict[int, Dict[str, List]]:
    """
    根据违例记录，提取每艘船在违例区域内的轨迹段，
    供 pydeck PathLayer 渲染红色高亮。

    Args:
        traj_df: 原始轨迹 DataFrame
        violation_df: check_all_zones 返回的违例 DataFrame

    Returns:
        Dict[vessel_id -> {
            "paths": [[lon, lat], ...] 的列表（每段一段）,
            "zone_names": 对应的区域名列表
        }]
    """
    result: Dict[int, Dict[str, Any]] = {}

    for _, row in violation_df.iterrows():
        vid = row["vessel_id"]
        zone_name = row["zone_name"]

        # 从原始轨迹中筛出该船在 first_entry ~ last_exit 时间范围内的点
        vdf = traj_df[
            (traj_df["vessel_id"] == vid)
            & (traj_df["time"] >= pd.Timestamp(row["first_entry"]))
            & (traj_df["time"] <= pd.Timestamp(row["last_exit"]))
        ].sort_values("time")

        if len(vdf) < 2:
            continue

        path = [[float(r.lon), float(r.lat)] for _, r in vdf.iterrows()]

        if vid not in result:
            result[vid] = {"paths": [], "zone_names": []}
        result[vid]["paths"].append(path)
        result[vid]["zone_names"].append(zone_name)

    return result


def _empty_violation_df() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "vessel_id", "zone_name", "zone_type",
        "first_entry", "last_exit", "duration_h",
        "n_entries", "n_points", "entry_lat", "entry_lon",
    ])


def summarize_violations(violations: pd.DataFrame) -> str:
    """将违例 DataFrame 生成文本摘要，供 UI 展示。"""
    if violations is None or len(violations) == 0:
        return "未发现进入禁航区域的船只。"

    total_vessels = violations["vessel_id"].nunique()
    total_zones = violations["zone_name"].nunique()
    top_vessels = (
        violations.groupby("vessel_id")["n_entries"]
        .sum()
        .sort_values(ascending=False)
        .head(3)
    )
    top_zones = (
        violations.groupby("zone_name")["vessel_id"]
        .nunique()
        .sort_values(ascending=False)
        .head(3)
    )

    parts = [
        f"检测到 **{total_vessels}** 艘船进入禁航区，涉及 **{total_zones}** 个区域：\n"
    ]
    if len(top_vessels) > 0:
        parts.append("违例最多的船只：")
        for vid, n in top_vessels.items():
            parts.append(f"  - 船 **{int(vid)}**：共进入 **{n}** 次")
    if len(top_zones) > 0:
        parts.append("最频繁进入的区域：")
        for zone, n in top_zones.items():
            parts.append(f"  - **{zone}**：**{n}** 艘船进入")

    return "\n".join(parts)
