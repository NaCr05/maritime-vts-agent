"""
AIS 数据查询模块
在 AISLoader 基础上封装常用查询接口，
并生成可供 RAG 使用的知识文本。
"""
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional
from .ais_loader import AISLoader


class AISQuery:
    def __init__(self, loader: Optional[AISLoader] = None):
        self.loader = loader or AISLoader()
        self._df: Optional[pd.DataFrame] = None

    def load(self) -> "AISQuery":
        self._df = self.loader.load_all()
        return self

    @property
    def df(self) -> pd.DataFrame:
        if self._df is None:
            self.load()
        return self._df

    def vessel_summary(self, vessel_id: int) -> dict:
        """返回指定船只的统计摘要。"""
        df = self.df
        vdf = df[df["vessel_id"] == vessel_id]
        if len(vdf) == 0:
            return {}

        sog = vdf["sog"]
        cog = vdf["cog"]
        time_range = (vdf["time"].max() - vdf["time"].min())

        # 计算航程（简单 Haversine 近似）
        total_distance = self._calc_total_distance(vdf)

        # 停泊段识别（速度 < 0.5 节）
        stopped = vdf[vdf["sog"] < 0.5]
        stopped_ratio = len(stopped) / len(vdf) * 100

        # 找出停泊位置（取停泊段中心点的平均值）
        stopped_positions = []
        if len(stopped) > 0:
            stopped_positions = [
                {"lat": float(r.lat), "lon": float(r.lon)}
                for _, r in stopped.iterrows()
            ]

        # 速度分段统计
        speed_buckets = {
            "停泊 (0-0.5kn)": float((sog < 0.5).sum()),
            "低速 (0.5-3kn)": float(((sog >= 0.5) & (sog < 3)).sum()),
            "中速 (3-6kn)": float(((sog >= 3) & (sog < 6)).sum()),
            "高速 (>6kn)": float((sog >= 6).sum()),
        }

        return {
            "vessel_id": int(vessel_id),
            "n_points": len(vdf),
            "time_start": str(vdf["time"].min()),
            "time_end": str(vdf["time"].max()),
            "duration_hours": round(time_range.total_seconds() / 3600, 1),
            "lat_center": round(float(vdf["lat"].mean()), 5),
            "lon_center": round(float(vdf["lon"].mean()), 5),
            "lat_range": [round(float(vdf["lat"].min()), 5),
                          round(float(vdf["lat"].max()), 5)],
            "lon_range": [round(float(vdf["lon"].min()), 5),
                          round(float(vdf["lon"].max()), 5)],
            "sog_min": round(float(sog.min()), 1),
            "sog_max": round(float(sog.max()), 1),
            "sog_mean": round(float(sog.mean()), 1),
            "sog_median": round(float(sog.median()), 1),
            "cog_mean": round(float(cog.mean()), 1),
            "total_distance_nm": round(total_distance, 1),
            "stopped_ratio_pct": round(stopped_ratio, 1),
            "n_stopped_points": len(stopped),
            "speed_buckets": speed_buckets,
            "stopped_positions_sample": stopped_positions[:10],
        }

    def multi_vessel_comparison(self, vessel_ids: list[int]) -> dict:
        """对比多艘船的统计信息。"""
        result = {}
        for vid in vessel_ids:
            result[vid] = self.vessel_summary(vid)
        return result

    def get_trajectory(
        self,
        vessel_id: int,
        time_start: Optional[pd.Timestamp] = None,
        time_end: Optional[pd.Timestamp] = None,
    ) -> pd.DataFrame:
        """获取轨迹（可按时间切片）。"""
        df = self.df
        vdf = df[df["vessel_id"] == vessel_id].copy()
        if time_start:
            vdf = vdf[vdf["time"] >= time_start]
        if time_end:
            vdf = vdf[vdf["time"] <= time_end]
        return vdf.sort_values("time")

    def get_multi_trajectories(
        self,
        vessel_ids: list[int],
        time_start: Optional[pd.Timestamp] = None,
        time_end: Optional[pd.Timestamp] = None,
    ) -> pd.DataFrame:
        """获取多船轨迹。"""
        df = self.df
        mask = df["vessel_id"].isin(vessel_ids)
        if time_start:
            mask &= df["time"] >= time_start
        if time_end:
            mask &= df["time"] <= time_end
        return df[mask].sort_values("time")

    def generate_rag_knowledge(self, vessel_id: int) -> str:
        """生成船只的 RAG 知识文本，用于注入知识库。"""
        s = self.vessel_summary(vessel_id)
        if not s:
            return f"未找到渔船 ID {vessel_id} 的数据。"

        lines = [
            f"渔船 {vessel_id} 的航行记录摘要：",
            f"数据点数：{s['n_points']} 个，",
            f"记录时间范围：{s['time_start']} 至 {s['time_end']}，",
            f"总航行时长：约 {s['duration_hours']} 小时，",
            f"航速统计：平均 {s['sog_mean']} 节，最高 {s['sog_max']} 节，最低 {s['sog_min']} 节，中位数 {s['sog_median']} 节，",
            f"航向平均方向：{s['cog_mean']} 度（0=北，90=东），",
            f"地理活动范围：纬度 {s['lat_range'][0]}°N ~ {s['lat_range'][1]}°N，",
            f"经度 {s['lon_range'][0]}°E ~ {s['lon_range'][1]}°E，",
            f"活动中心：约 {s['lat_center']}°N, {s['lon_center']}°E，",
            f"估算总航程：约 {s['total_distance_nm']} 海里，",
            f"停泊时间占比：{s['stopped_ratio_pct']}%（速度低于 0.5 节视为停泊），",
        ]

        sb = s["speed_buckets"]
        lines.append(
            f"速度分布：停泊 {sb['停泊 (0-0.5kn)']:.0f} 点，"
            f"低速 {sb['低速 (0.5-3kn)']:.0f} 点，"
            f"中速 {sb['中速 (3-6kn)']:.0f} 点，"
            f"高速 {sb['高速 (>6kn)']:.0f} 点。"
        )

        return "".join(lines)

    def generate_all_knowledge(self) -> list[str]:
        """为所有船只生成 RAG 知识文本（知识库构建用）。"""
        knowledge_list = []
        for meta in self.loader.registry:
            vid = meta["vessel_id"]
            text = self.generate_rag_knowledge(vid)
            knowledge_list.append(text)
        return knowledge_list

    @staticmethod
    def _calc_total_distance(df: pd.DataFrame) -> float:
        """使用 Haversine 公式估算相邻点间总航程（海里）。"""
        if len(df) < 2:
            return 0.0

        lats = np.radians(df["lat"].values)
        lons = np.radians(df["lon"].values)
        dlat = np.diff(lats)
        dlon = np.diff(lons)

        a = np.sin(dlat / 2) ** 2 + np.cos(lats[:-1]) * np.cos(lats[1:]) * np.sin(dlon / 2) ** 2
        c = 2 * np.arcsin(np.sqrt(a))
        nm_per_rad = 180 * 60 / np.pi
        return float(np.sum(c * nm_per_rad))

    @staticmethod
    def haversine_distance(
        lat1: float, lon1: float,
        lat2: float, lon2: float
    ) -> float:
        """两点间 Haversine 距离（海里）。"""
        R = 180 * 60 / np.pi
        phi1, phi2 = np.radians(lat1), np.radians(lat2)
        dphi = np.radians(lat2 - lat1)
        dlam = np.radians(lon2 - lon1)
        a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
        return float(2 * np.arcsin(np.sqrt(a)) * R)
