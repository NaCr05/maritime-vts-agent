"""
Rule-based voyage segmentation for AIS trajectories.

The splitter treats long consecutive low-speed periods as berth/anchorage
boundaries, and returns the moving trajectory windows between those
boundaries as voyages.
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd

from src.ais_query import AISQuery


VOYAGE_COLUMNS = [
    "vessel_id",
    "trip_id",
    "start_time",
    "end_time",
    "duration_h",
    "n_points",
    "distance_nm",
    "avg_sog",
    "max_sog",
    "start_lat",
    "start_lon",
    "end_lat",
    "end_lon",
]


def segment_voyages(
    traj_df: pd.DataFrame,
    stop_threshold: float = 0.5,
    min_stop_hours: float = 3.0,
    min_trip_hours: float = 1.0,
) -> pd.DataFrame:
    """Segment one or more AIS trajectories into voyages.

    Args:
        traj_df: DataFrame with vessel_id, time, lat, lon, sog columns.
        stop_threshold: SOG below this value is treated as stopped.
        min_stop_hours: Consecutive stopped blocks at least this long become
            trip boundaries.
        min_trip_hours: Shorter moving windows are ignored.

    Returns:
        DataFrame with one row per detected voyage.
    """
    required = {"vessel_id", "time", "lat", "lon", "sog"}
    if traj_df is None or len(traj_df) == 0 or not required.issubset(traj_df.columns):
        return _empty_voyages()

    rows: list[dict] = []
    for vessel_id, vdf in traj_df.groupby("vessel_id"):
        rows.extend(
            _segment_single_vessel(
                vdf,
                int(vessel_id),
                stop_threshold=stop_threshold,
                min_stop_hours=min_stop_hours,
                min_trip_hours=min_trip_hours,
            )
        )

    if not rows:
        return _empty_voyages()

    return pd.DataFrame(rows, columns=VOYAGE_COLUMNS).sort_values(
        ["vessel_id", "start_time"]
    ).reset_index(drop=True)


def segment_voyages_for_ids(
    ais_query: AISQuery,
    vessel_ids: Iterable[int],
    stop_threshold: float = 0.5,
    min_stop_hours: float = 3.0,
    min_trip_hours: float = 1.0,
) -> pd.DataFrame:
    """Convenience wrapper for segmenting selected vessels from AISQuery."""
    vessel_ids = [int(v) for v in vessel_ids]
    if not vessel_ids:
        return _empty_voyages()
    traj_df = ais_query.get_multi_trajectories(vessel_ids)
    return segment_voyages(
        traj_df,
        stop_threshold=stop_threshold,
        min_stop_hours=min_stop_hours,
        min_trip_hours=min_trip_hours,
    )


def summarize_voyages(voyages: pd.DataFrame) -> str:
    """Return a concise Markdown summary for detected voyages."""
    if voyages is None or len(voyages) == 0:
        return "当前参数下没有识别出有效航次。可以降低最小航次时长，或缩短停泊边界时长。"

    total_distance = float(voyages["distance_nm"].sum())
    total_duration = float(voyages["duration_h"].sum())
    n_vessels = int(voyages["vessel_id"].nunique())
    longest = voyages.sort_values("distance_nm", ascending=False).iloc[0]
    return (
        f"识别出 **{len(voyages)}** 个航次，涉及 **{n_vessels}** 艘船；"
        f"累计航程约 **{total_distance:.1f} nm**，累计航行时长约 **{total_duration:.1f} h**。"
        f"最长航次为船 **{int(longest['vessel_id'])}** 的第 **{int(longest['trip_id'])}** 航次，"
        f"约 **{float(longest['distance_nm']):.1f} nm**。"
    )


def _segment_single_vessel(
    vdf: pd.DataFrame,
    vessel_id: int,
    stop_threshold: float,
    min_stop_hours: float,
    min_trip_hours: float,
) -> list[dict]:
    vdf = vdf.dropna(subset=["time", "lat", "lon", "sog"]).copy()
    if len(vdf) < 2:
        return []

    vdf["time"] = pd.to_datetime(vdf["time"])
    vdf = vdf.sort_values("time").reset_index(drop=True)
    vdf["is_stop"] = vdf["sog"] < stop_threshold
    vdf["state_block"] = (vdf["is_stop"] != vdf["is_stop"].shift()).cumsum()

    boundary_blocks: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for _, block in vdf[vdf["is_stop"]].groupby("state_block"):
        start = pd.Timestamp(block["time"].iloc[0])
        end = pd.Timestamp(block["time"].iloc[-1])
        duration_h = (end - start).total_seconds() / 3600
        if duration_h >= min_stop_hours:
            boundary_blocks.append((start, end))

    windows: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    cursor = pd.Timestamp(vdf["time"].iloc[0])
    for stop_start, stop_end in boundary_blocks:
        if stop_start > cursor:
            windows.append((cursor, stop_start))
        cursor = stop_end
    last_time = pd.Timestamp(vdf["time"].iloc[-1])
    if cursor < last_time:
        windows.append((cursor, last_time))

    rows: list[dict] = []
    trip_id = 1
    for start, end in windows:
        segment = vdf[(vdf["time"] >= start) & (vdf["time"] <= end)].copy()
        moving = segment[segment["sog"] >= stop_threshold]
        if len(segment) < 2 or len(moving) == 0:
            continue

        trip_start = pd.Timestamp(segment["time"].iloc[0])
        trip_end = pd.Timestamp(segment["time"].iloc[-1])
        duration_h = (trip_end - trip_start).total_seconds() / 3600
        if duration_h < min_trip_hours:
            continue

        distance_nm = AISQuery._calc_total_distance(segment)
        rows.append({
            "vessel_id": int(vessel_id),
            "trip_id": int(trip_id),
            "start_time": trip_start.strftime("%Y-%m-%d %H:%M"),
            "end_time": trip_end.strftime("%Y-%m-%d %H:%M"),
            "duration_h": round(duration_h, 1),
            "n_points": int(len(segment)),
            "distance_nm": round(float(distance_nm), 1),
            "avg_sog": round(float(segment["sog"].mean()), 2),
            "max_sog": round(float(segment["sog"].max()), 2),
            "start_lat": round(float(segment["lat"].iloc[0]), 5),
            "start_lon": round(float(segment["lon"].iloc[0]), 5),
            "end_lat": round(float(segment["lat"].iloc[-1]), 5),
            "end_lon": round(float(segment["lon"].iloc[-1]), 5),
        })
        trip_id += 1

    return rows


def _empty_voyages() -> pd.DataFrame:
    return pd.DataFrame(columns=VOYAGE_COLUMNS)
