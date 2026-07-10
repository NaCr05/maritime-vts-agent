"""
AIS 数据集快速扫描脚本
扫描 dataset/ 下所有 CSV，汇总元数据
"""
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import json

DATASET_DIR = Path(__file__).parent.parent / "dataset"
OUTPUT_FILE = Path(__file__).parent.parent / "data" / "vessel_summary.json"


def scan_vessel(csv_path: Path) -> dict | None:
    try:
        df = pd.read_csv(csv_path, encoding="utf-8")
    except Exception:
        try:
            df = pd.read_csv(csv_path, encoding="gbk")
        except Exception:
            return None

    if len(df) == 0:
        return None

    col_map = {}
    for col in df.columns:
        col_lower = col.lower().strip()
        if col in ["渔船ID", "vessel_id", "ship_id"]:
            col_map[col] = "vessel_id"
        elif col in ["lat", "LAT", "纬度", "latitude"]:
            col_map[col] = "lat"
        elif col in ["lon", "LON", "经度", "longitude"]:
            col_map[col] = "lon"
        elif col in ["速度", "sog", "SOG", "speed"]:
            col_map[col] = "sog"
        elif col in ["方向", "cog", "COG", "heading", "direction"]:
            col_map[col] = "cog"
        elif col in ["time", "Time", "TIMESTAMP", "时间", "timestamp"]:
            col_map[col] = "time"
        elif col in ["vessel_name", "VesselName", "船名", "name"]:
            col_map[col] = "vessel_name"

    for old, new in col_map.items():
        df.rename(columns={old: new}, inplace=True)

    required = ["vessel_id", "lat", "lon", "sog", "cog", "time"]
    if not all(c in df.columns for c in required):
        return None

    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time", "lat", "lon"])

    if len(df) == 0:
        return None

    vessel_id = int(df["vessel_id"].iloc[0])
    lat_min = float(df["lat"].min())
    lat_max = float(df["lat"].max())
    lon_min = float(df["lon"].min())
    lon_max = float(df["lon"].max())
    sog_min = float(df["sog"].min())
    sog_max = float(df["sog"].max())
    sog_mean = float(df["sog"].mean())
    time_min = df["time"].min().isoformat()
    time_max = df["time"].max().isoformat()
    n_points = len(df)

    duration_hours = (df["time"].max() - df["time"].min()).total_seconds() / 3600
    sample_rate_min = (
        df["time"].sort_values().diff().dropna().dt.total_seconds().median() / 60
        if len(df) > 1
        else None
    )

    # 速度为0的点数（可能表示停泊/锚地）
    n_stopped = int((df["sog"] < 0.5).sum())

    return {
        "vessel_id": vessel_id,
        "n_points": n_points,
        "time_start": time_min,
        "time_end": time_max,
        "lat_range": [lat_min, lat_max],
        "lon_range": [lon_min, lon_max],
        "sog_range": [round(sog_min, 1), round(sog_max, 1)],
        "sog_mean": round(sog_mean, 1),
        "duration_hours": round(duration_hours, 1),
        "sample_rate_min": round(sample_rate_min, 1) if sample_rate_min else None,
        "n_stopped_points": n_stopped,
        "stopped_ratio": round(n_stopped / n_points * 100, 1),
        "filename": csv_path.name,
    }


def main():
    csv_files = sorted(DATASET_DIR.glob("*.csv"))
    print(f"找到 {len(csv_files)} 个 CSV 文件，开始扫描...")

    results = []
    for i, f in enumerate(csv_files):
        meta = scan_vessel(f)
        if meta:
            results.append(meta)
            print(f"  [{i+1:3d}/{len(csv_files)}] {meta['vessel_id']:6d}  "
                  f"| {meta['n_points']:5d} 点 "
                  f"| {meta['time_start'][:10]} ~ {meta['time_end'][:10]} "
                  f"| 停泊率 {meta['stopped_ratio']}%")
        else:
            print(f"  [{i+1:3d}/{len(csv_files)}] {f.name} -- 解析失败，跳过")

    print(f"\n成功扫描 {len(results)} 个有效文件")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fp:
        json.dump(results, fp, ensure_ascii=False, indent=2)
    print(f"结果已保存到: {OUTPUT_FILE}")

    # ===== 汇总统计 =====
    print("\n" + "=" * 60)
    print("【汇总统计】")
    print("=" * 60)

    n_points_list = [r["n_points"] for r in results]
    durations = [r["duration_hours"] for r in results]
    stopped_ratios = [r["stopped_ratio"] for r in results]

    print(f"船只总数:       {len(results)} 艘")
    print(f"总数据点数:     {sum(n_points_list):,} 点")
    print(f"平均每船点数:   {np.mean(n_points_list):.0f} 点")
    print(f"最多点数船只:   {max(n_points_list)} 点")
    print(f"最少点数船只:   {min(n_points_list)} 点")
    print(f"平均航行时长:   {np.mean(durations):.1f} 小时")
    print(f"平均采样间隔:   {np.median([r['sample_rate_min'] for r in results if r['sample_rate_min']]):.0f} 分钟")

    print(f"\n平均停泊率:     {np.mean(stopped_ratios):.1f}%")
    print(f"停泊率 > 50% 的船: {sum(1 for r in stopped_ratios if r > 50)} 艘  "
          f"（可能是作业渔船）")
    print(f"停泊率 < 5% 的船:  {sum(1 for r in stopped_ratios if r < 5)} 艘   "
          f"（持续航行）")

    # 时间重叠分析
    all_times = []
    for r in results:
        t_start = pd.Timestamp(r["time_start"])
        t_end = pd.Timestamp(r["time_end"])
        all_times.append((t_start, t_end, r["vessel_id"]))

    all_times.sort(key=lambda x: x[0])

    # 找出时间窗口重叠的船对
    overlapping_pairs = []
    for i in range(len(all_times)):
        for j in range(i + 1, len(all_times)):
            s1, e1, id1 = all_times[i]
            s2, e2, id2 = all_times[j]
            if s1 <= e2 and s2 <= e1:  # 有重叠
                overlap = min(e1, e2) - max(s1, s2)
                overlapping_pairs.append((id1, id2, s1.date(), s2.date(), str(overlap)))

    # 按月份分组
    month_counts = {}
    for r in results:
        month = r["time_start"][:7]
        month_counts[month] = month_counts.get(month, 0) + 1

    print(f"\n按月份船只分布（船只可能跨月）:")
    for month, count in sorted(month_counts.items()):
        print(f"  {month}: {count} 艘")

    if overlapping_pairs:
        print(f"\n时间重叠的船对: {len(overlapping_pairs)} 对（可做多船联合分析）")
        # 取前 5 对展示
        for pair in overlapping_pairs[:5]:
            print(f"  船 {pair[0]} & 船 {pair[1]}  | 船1覆盖 {pair[2]}  船2覆盖 {pair[3]}  重叠 {pair[4]}")
    else:
        print("\n时间重叠的船对: 0 对（所有船不在同一时段活跃）")

    # 地理范围
    lats = [r["lat_range"] for r in results]
    lons = [r["lon_range"] for r in results]
    all_lats = [v for rng in lats for v in rng]
    all_lons = [v for rng in lons for v in rng]
    print(f"\n地理范围:")
    print(f"  LAT: {min(all_lats):.4f}°N ~ {max(all_lats):.4f}°N")
    print(f"  LON: {min(all_lons):.4f}°E ~ {max(all_lons):.4f}°E")

    # 判断主要海域
    mid_lat = (min(all_lats) + max(all_lats)) / 2
    mid_lon = (min(all_lons) + max(all_lons)) / 2
    print(f"  中心: {mid_lat:.4f}°N, {mid_lon:.4f}°E")

    if 30 <= mid_lat <= 32 and 121 <= mid_lon <= 124:
        print("  -> 东海长江口/舟山渔场水域")


if __name__ == "__main__":
    main()
