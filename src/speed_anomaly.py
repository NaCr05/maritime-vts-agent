"""
航速异常检测模块（Z-Score 方法）

用法：
    from src.speed_anomaly import detect_by_vessel, detect_global
    anomalies = detect_by_vessel(all_traj, threshold=2.5, min_n=5)

异常判定规则：
    Z = (sog - μ) / σ
    |Z| > threshold → 异常
    Z > 0  → 航速过高（突增）
    Z < 0  → 航速过低（突停）

停泊过滤策略：
    连续停泊段（连续 N 条记录 sog < stop_threshold）被整体切除，
    避免大量 0 值把 σ 拉低导致微量波动也判异常。

接口约定（与 ais_query.py 返回的 DataFrame 对齐）：
    all_traj 必须包含列：vessel_id, time, lat, lon, sog, cog
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from typing import Optional


def _filter_moored_segments(
    vdf: pd.DataFrame,
    stop_threshold: float = 0.5,
    min_run: int = 3,
) -> pd.DataFrame:
    """切除连续停泊段，保留行索引。

    连续 `min_run` 条及以上 sog < stop_threshold 的段整体切除。
    返回一个新的 DataFrame（仅保留非停泊段行）。
    """
    sog = vdf["sog"].values
    is_stop = (sog < stop_threshold).astype(int)
    if len(is_stop) == 0:
        return vdf.iloc[[]]

    # 找出停泊段起始/结束（状态切换）
    diff = np.diff(is_stop, prepend=0, append=0)
    starts = np.where(diff == 1)[0]
    ends = np.where(diff == -1)[0]
    # 只保留长度 >= min_run 的段
    drop_mask = np.zeros(len(vdf), dtype=bool)
    for s, e in zip(starts, ends):
        if (e - s) >= min_run:
            drop_mask[s:e] = True

    return vdf.loc[~drop_mask].copy()


def detect_by_vessel(
    all_traj: pd.DataFrame,
    threshold: float = 2.5,
    min_n: int = 5,
    stop_threshold: float = 0.5,
    min_stop_run: int = 3,
) -> pd.DataFrame:
    """按船单独计算 μ、σ，做 Z-Score 异常检测。

    Args:
        all_traj: ais_query.get_multi_trajectories() 返回的 DataFrame
        threshold: Z-Score 绝对值阈值（默认 2.5，约 99% 置信区间）
        min_n: 至少需要 N 条有效（非停泊）记录，否则跳过该船
        stop_threshold: 小于该速度视为停泊
        min_stop_run: 连续多少条停泊才切除

    Returns:
        DataFrame，列：vessel_id, time, lat, lon, sog, z_score,
        sog_mean, sog_std, anomaly_type
        其中 anomaly_type 可为 "过高"/"过低"/None
    """
    rows: list[dict] = []

    for vid, vdf in all_traj.groupby("vessel_id", sort=False):
        vdf = vdf.sort_values("time").copy()
        if len(vdf) < 2:
            continue

        clean = _filter_moored_segments(
            vdf,
            stop_threshold=stop_threshold,
            min_run=min_stop_run,
        )
        if len(clean) < min_n:
            continue

        sog = clean["sog"].astype(float)
        mean = float(sog.mean())
        std = float(sog.std(ddof=1))
        if std < 1e-6:
            # 所有非停泊段速度几乎相同，跳过
            continue

        z = (sog - mean) / std
        mask = z.abs() > threshold

        if not mask.any():
            continue

        anomaly_df = clean.loc[mask, ["vessel_id", "time", "lat", "lon", "sog"]].copy()
        anomaly_df["z_score"] = z[mask].round(3)
        anomaly_df["sog_mean"] = round(mean, 2)
        anomaly_df["sog_std"] = round(std, 2)
        anomaly_df["anomaly_type"] = np.where(
            anomaly_df["sog"] > mean, "过高", "过低"
        )
        rows.append(anomaly_df)

    if not rows:
        return pd.DataFrame(columns=[
            "vessel_id", "time", "lat", "lon", "sog",
            "z_score", "sog_mean", "sog_std", "anomaly_type",
        ])

    out = pd.concat(rows, ignore_index=True)
    out = out.sort_values(["vessel_id", "time"]).reset_index(drop=True)
    return out


def detect_global(
    all_traj: pd.DataFrame,
    threshold: float = 2.5,
    stop_threshold: float = 0.5,
    min_stop_run: int = 3,
) -> pd.DataFrame:
    """用全局 μ、σ 做 Z-Score 异常检测（把所有船的航速合在一起算）。

    适用于：希望渔船和货船共享同一速度基线，或数据量极少无法按船统计。
    返回格式与 detect_by_vessel 相同，但 sog_mean/sog_std 为全局值。
    """
    all_traj = all_traj.sort_values("time").copy()
    clean = _filter_moored_segments(
        all_traj,
        stop_threshold=stop_threshold,
        min_run=min_stop_run,
    )
    if len(clean) < 2:
        return pd.DataFrame(columns=[
            "vessel_id", "time", "lat", "lon", "sog",
            "z_score", "sog_mean", "sog_std", "anomaly_type",
        ])

    sog = clean["sog"].astype(float)
    mean = float(sog.mean())
    std = float(sog.std(ddof=1))
    if std < 1e-6:
        return pd.DataFrame(columns=[
            "vessel_id", "time", "lat", "lon", "sog",
            "z_score", "sog_mean", "sog_std", "anomaly_type",
        ])

    z = (sog - mean) / std
    mask = z.abs() > threshold

    out = clean.loc[mask, ["vessel_id", "time", "lat", "lon", "sog"]].copy()
    if len(out) == 0:
        return pd.DataFrame(columns=[
            "vessel_id", "time", "lat", "lon", "sog",
            "z_score", "sog_mean", "sog_std", "anomaly_type",
        ])

    out["z_score"] = z[mask].round(3)
    out["sog_mean"] = round(mean, 2)
    out["sog_std"] = round(std, 2)
    out["anomaly_type"] = np.where(out["sog"] > mean, "过高", "过低")
    out = out.sort_values(["vessel_id", "time"]).reset_index(drop=True)
    return out


def summarize_anomalies(anomalies: pd.DataFrame) -> str:
    """把异常 DataFrame 变成可读文本摘要，供侧边栏展示。"""
    if anomalies is None or len(anomalies) == 0:
        return "未发现航速异常。"

    parts: list[str] = [f"检测到 **{len(anomalies)}** 处航速异常：\n"]
    for _, r in anomalies.iterrows():
        direction = "↑ 过高" if r["anomaly_type"] == "过高" else "↓ 过低"
        parts.append(
            f"- 船 **{int(r['vessel_id'])}**，"
            f"时间 `{pd.Timestamp(r['time']).strftime('%Y-%m-%d %H:%M')}`，"
            f"航速 **{r['sog']:.1f} kn**，"
            f"Z={r['z_score']:+.1f}（均值 {r['sog_mean']} kn，σ {r['sog_std']}）{direction}"
        )
    return "\n".join(parts)
