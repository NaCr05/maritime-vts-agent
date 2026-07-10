"""
AIS 数据加载模块
将 dataset/ 下所有 CSV 统一加载为标准 DataFrame，
并生成船只注册表（vessel_registry）和时间索引。
"""
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional
import json

DATASET_DIR = Path(__file__).parent.parent / "dataset"
SUMMARY_FILE = Path(__file__).parent.parent / "data" / "vessel_summary.json"


class AISLoader:
    def __init__(self, dataset_dir: Path = DATASET_DIR):
        self.dataset_dir = dataset_dir
        self.csv_files = sorted(dataset_dir.glob("*.csv"))
        self._registry: list[dict] = []
        self._all_data: Optional[pd.DataFrame] = None

    def _load_single(self, path: Path) -> pd.DataFrame | None:
        for enc in ("utf-8", "gbk"):
            try:
                df = pd.read_csv(path, encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            return None

        col_map = {}
        for col in df.columns:
            col_l = col.lower().strip()
            if col in ("渔船ID", "vessel_id", "ship_id"):
                col_map[col] = "vessel_id"
            elif col in ("lat", "LAT", "纬度", "latitude"):
                col_map[col] = "lat"
            elif col in ("lon", "LON", "经度", "longitude"):
                col_map[col] = "lon"
            elif col in ("速度", "sog", "SOG", "speed"):
                col_map[col] = "sog"
            elif col in ("方向", "cog", "COG", "heading", "direction"):
                col_map[col] = "cog"
            elif col in ("time", "Time", "TIMESTAMP", "时间", "timestamp"):
                col_map[col] = "time"

        df.rename(columns=col_map, inplace=True)

        required = {"vessel_id", "lat", "lon", "sog", "cog", "time"}
        if not required.issubset(df.columns):
            return None

        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df["vessel_id"] = pd.to_numeric(df["vessel_id"], errors="coerce")
        df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
        df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
        df["sog"] = pd.to_numeric(df["sog"], errors="coerce")
        df["cog"] = pd.to_numeric(df["cog"], errors="coerce")
        df.dropna(subset=["time", "vessel_id", "lat", "lon"], inplace=True)
        df["vessel_id"] = df["vessel_id"].astype(int)
        df.sort_values("time", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    def load_all(self, use_summary: bool = True) -> pd.DataFrame:
        """
        加载全部 CSV 并拼接成一个 DataFrame。
        use_summary=True 时优先从 vessel_summary.json 读取元数据，
        避免重复解析所有文件头。
        """
        if use_summary and SUMMARY_FILE.exists():
            return self._load_from_summary()

        frames = []
        for path in self.csv_files:
            df = self._load_single(path)
            if df is not None and len(df) > 0:
                frames.append(df)

        self._all_data = pd.concat(frames, ignore_index=True)
        self._build_registry()
        return self._all_data

    def _load_from_summary(self) -> pd.DataFrame:
        with open(SUMMARY_FILE, encoding="utf-8") as f:
            summary = json.load(f)

        self._registry = summary
        frames = []
        for meta in summary:
            path = self.dataset_dir / meta["filename"]
            df = self._load_single(path)
            if df is not None:
                frames.append(df)

        self._all_data = pd.concat(frames, ignore_index=True)
        return self._all_data

    def _build_registry(self):
        if self._all_data is None:
            return
        grouped = self._all_data.groupby("vessel_id")
        self._registry = []
        for vid, grp in grouped:
            lat_min, lat_max = float(grp.lat.min()), float(grp.lat.max())
            lon_min, lon_max = float(grp.lon.min()), float(grp.lon.max())
            self._registry.append({
                "vessel_id": int(vid),
                "n_points": len(grp),
                "time_start": grp.time.min().isoformat(),
                "time_end": grp.time.max().isoformat(),
                "lat_range": [lat_min, lat_max],
                "lon_range": [lon_min, lon_max],
                "sog_range": [float(grp.sog.min()), float(grp.sog.max())],
                "sog_mean": round(float(grp.sog.mean()), 1),
                "duration_hours": round(
                    (grp.time.max() - grp.time.min()).total_seconds() / 3600, 1
                ),
                "stopped_ratio": round(
                    float((grp.sog < 0.5).sum() / len(grp) * 100), 1
                ),
            })

    @property
    def registry(self) -> list[dict]:
        if not self._registry:
            self.load_all()
        return self._registry

    @property
    def all_data(self) -> pd.DataFrame:
        if self._all_data is None:
            self.load_all()
        return self._all_data

    def get_vessel(self, vessel_id: int) -> pd.DataFrame | None:
        """按船 ID 获取该船全部轨迹点。"""
        df = self.all_data
        result = df[df["vessel_id"] == vessel_id].copy()
        return result if len(result) > 0 else None

    def get_vessels_by_time(
        self, time_start: pd.Timestamp, time_end: pd.Timestamp
    ) -> list[int]:
        """获取指定时间窗口内活跃的所有船只 ID。"""
        df = self.all_data
        mask = (df["time"] >= time_start) & (df["time"] <= time_end)
        return sorted(df.loc[mask, "vessel_id"].unique().tolist())

    def get_vessels_by_area(
        self,
        lat_min: float, lat_max: float,
        lon_min: float, lon_max: float,
    ) -> list[int]:
        """获取指定地理矩形区域内出现过的所有船只 ID。"""
        df = self.all_data
        mask = (
            (df["lat"] >= lat_min) & (df["lat"] <= lat_max) &
            (df["lon"] >= lon_min) & (df["lon"] <= lon_max)
        )
        return sorted(df.loc[mask, "vessel_id"].unique().tolist())

    def get_vessels_by_month(self, year: int, month: int) -> list[dict]:
        """获取指定年月的船只列表及其元数据。"""
        vessels = []
        for meta in self.registry:
            ts = pd.Timestamp(meta["time_start"])
            te = pd.Timestamp(meta["time_end"])
            m_start = pd.Timestamp(f"{year}-{month:02d}-01")
            if month == 12:
                m_end = pd.Timestamp(f"{year+1}-01-01")
            else:
                m_end = pd.Timestamp(f"{year}-{month+1:02d}-01")
            if ts < m_end and te >= m_start:
                vessels.append(meta)
        return vessels
