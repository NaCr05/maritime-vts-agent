"""
DBSCAN-based anchorage / stay-point detection for AIS low-speed points.

The detector clusters low-speed AIS points with a haversine distance metric.
It is intended for demo analysis: cluster centers can indicate likely
anchorage, fishing grounds, or repeated low-speed operating areas.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

from src.geo_fence import haversine_nm


EARTH_RADIUS_NM = 3440.065


def detect_anchor_clusters(
    traj_df: pd.DataFrame,
    stop_threshold: float = 0.5,
    eps_nm: float = 1.0,
    min_samples: int = 20,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Cluster low-speed AIS points into likely anchorage / stay areas.

    Args:
        traj_df: DataFrame with vessel_id, time, lat, lon, sog columns.
        stop_threshold: Points below this SOG are treated as stopped/loitering.
        eps_nm: DBSCAN neighborhood radius in nautical miles.
        min_samples: Minimum points required to form a cluster.

    Returns:
        (clusters, clustered_points)

        clusters columns:
            cluster_id, center_lat, center_lon, n_points, n_vessels,
            first_time, last_time, duration_h, avg_sog, radius_nm

        clustered_points is the low-speed point DataFrame with a cluster_id
        column. Noise points have cluster_id == -1.
    """
    required = {"vessel_id", "time", "lat", "lon", "sog"}
    if traj_df is None or len(traj_df) == 0 or not required.issubset(traj_df.columns):
        return _empty_clusters(), _empty_points()

    stop_df = traj_df[traj_df["sog"] < stop_threshold].copy()
    stop_df = stop_df.dropna(subset=["vessel_id", "time", "lat", "lon", "sog"])
    if len(stop_df) == 0:
        return _empty_clusters(), _empty_points()

    coords_rad = np.radians(stop_df[["lat", "lon"]].to_numpy(dtype=float))
    eps_rad = eps_nm / EARTH_RADIUS_NM
    labels = DBSCAN(
        eps=eps_rad,
        min_samples=min_samples,
        metric="haversine",
    ).fit_predict(coords_rad)

    stop_df["cluster_id"] = labels.astype(int)

    rows: list[dict] = []
    for cluster_id, cdf in stop_df[stop_df["cluster_id"] >= 0].groupby("cluster_id"):
        center_lat = float(cdf["lat"].mean())
        center_lon = float(cdf["lon"].mean())
        radius_nm = 0.0
        if len(cdf) > 0:
            radius_nm = max(
                haversine_nm(center_lat, center_lon, float(r.lat), float(r.lon))
                for _, r in cdf.iterrows()
            )

        first_time = pd.Timestamp(cdf["time"].min())
        last_time = pd.Timestamp(cdf["time"].max())
        rows.append({
            "cluster_id": int(cluster_id),
            "center_lat": round(center_lat, 5),
            "center_lon": round(center_lon, 5),
            "n_points": int(len(cdf)),
            "n_vessels": int(cdf["vessel_id"].nunique()),
            "first_time": first_time.strftime("%Y-%m-%d %H:%M"),
            "last_time": last_time.strftime("%Y-%m-%d %H:%M"),
            "duration_h": round((last_time - first_time).total_seconds() / 3600, 1),
            "avg_sog": round(float(cdf["sog"].mean()), 2),
            "radius_nm": round(float(radius_nm), 2),
        })

    if not rows:
        return _empty_clusters(), stop_df.reset_index(drop=True)

    clusters = pd.DataFrame(rows).sort_values(
        ["n_points", "n_vessels"], ascending=False
    ).reset_index(drop=True)
    return clusters, stop_df.reset_index(drop=True)


def summarize_anchor_clusters(clusters: pd.DataFrame, points: pd.DataFrame) -> str:
    """Return a concise Markdown summary for the UI."""
    if clusters is None or len(clusters) == 0:
        n_noise = 0 if points is None or len(points) == 0 else int((points["cluster_id"] == -1).sum())
        return f"未识别出稳定停留簇。噪声/零散低速点：**{n_noise}** 个。"

    n_noise = int((points["cluster_id"] == -1).sum()) if points is not None and len(points) else 0
    top = clusters.iloc[0]
    return (
        f"识别出 **{len(clusters)}** 个疑似锚地/停留区，"
        f"噪声/零散低速点 **{n_noise}** 个。"
        f"最大停留簇位于 **{top['center_lat']}°N, {top['center_lon']}°E**，"
        f"包含 **{int(top['n_points'])}** 个低速点，涉及 **{int(top['n_vessels'])}** 艘船。"
    )


def _empty_clusters() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "cluster_id", "center_lat", "center_lon", "n_points", "n_vessels",
        "first_time", "last_time", "duration_h", "avg_sog", "radius_nm",
    ])


def _empty_points() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "vessel_id", "time", "lat", "lon", "sog", "cluster_id",
    ])
