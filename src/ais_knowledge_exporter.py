"""
AIS 数据导出为 RAG 知识库文本。

将 AIS 航行摘要（基于 ais_query.generate_rag_knowledge）批量写入
data/ais_knowledge/ 目录，供 document_loader.build_chunks 读取。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.ais_loader import AISLoader
    from src.ais_query import AISQuery
    from src.speed_anomaly import detect_by_vessel, detect_global


DEFAULT_OUTPUT_DIR_NAME = "ais_knowledge"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def export_vessel_knowledge(
    ais_query: "AISQuery",
    output_dir: Path,
    vessel_ids: Optional[list[int]] = None,
    prefix: str = "ais_knowledge/",
) -> int:
    """批量导出船只航行摘要。

    Args:
        ais_query: AISQuery 实例（已加载）
        output_dir: 输出目录（会被自动创建）
        vessel_ids: 指定船 ID 列表，None = 全部
        prefix: doc_name 前缀（用于区分来源，默认 "ais_knowledge/"）

    Returns:
        成功写入的文件数。
    """
    _ensure_dir(output_dir)
    if vessel_ids is None:
        vessel_ids = [m["vessel_id"] for m in ais_query.loader.registry]

    written = 0
    for vid in vessel_ids:
        try:
            text = ais_query.generate_rag_knowledge(vid)
        except Exception:
            continue
        fname = f"vessel_{vid}.txt"
        doc_name = f"{prefix}{fname}"
        (output_dir / fname).write_text(text, encoding="utf-8")
        written += 1

    return written


def export_anomaly_knowledge(
    ais_query: "AISQuery",
    anomalies,
    params: dict,
    output_dir: Path,
    prefix: str = "ais_knowledge/",
    filename: str = "anomaly_summary.txt",
) -> Optional[Path]:
    """将异常检测结果写入自然语言摘要文本。

    Args:
        ais_query: AISQuery 实例
        anomalies: detect_by_vessel/detect_global 返回的 DataFrame
        params: 本次检测参数（用于记录），如 {"threshold": 2.5, "mode": "by_vessel"}
        output_dir: 输出目录
        prefix: doc_name 前缀
        filename: 输出文件名

    Returns:
        写入文件的 Path；若 anomalies 为空则返回 None。
    """
    import pandas as pd

    _ensure_dir(output_dir)
    try:
        n_anomalies = int(len(anomalies))  # type: ignore[arg-type]
    except Exception:
        return None

    if n_anomalies == 0:
        return None

    vessel_ids = sorted(anomalies["vessel_id"].unique().tolist())  # type: ignore[index]
    lines: list[str] = [
        "航速异常检测结果汇总",
        f"检测时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"检测模式：{params.get('mode', 'by_vessel')}",
        f"Z-Score 阈值：{params.get('threshold', '?')}",
        f"最少记录数：{params.get('min_n', '?')}",
        f"异常记录总数：{n_anomalies} 条，涉及 {len(vessel_ids)} 艘船",
        "",
    ]

    for vid in vessel_ids:
        vdf = anomalies[anomalies["vessel_id"] == vid]  # type: ignore[index]
        lines.append(f"渔船 {vid}：异常 {len(vdf)} 条")
        for _, r in vdf.iterrows():
            direction = "过高" if r["anomaly_type"] == "过高" else "过低"
            lines.append(
                f"  - {pd.Timestamp(r['time']).strftime('%Y-%m-%d %H:%M')}，"
                f"航速 {r['sog']:.1f} kn，Z={r['z_score']:+.1f}（μ={r['sog_mean']}，σ={r['sog_std']}）{direction}"
            )
        lines.append("")

    text = "\n".join(lines)
    out_path = output_dir / filename
    out_path.write_text(text, encoding="utf-8")
    return out_path


def export_all_ais_knowledge(
    ais_query: "AISQuery",
    output_dir: Optional[Path] = None,
    prefix: str = "ais_knowledge/",
    include_anomaly: bool = False,
    anomalies=None,
    anomaly_params: Optional[dict] = None,
) -> dict:
    """一键导出所有 AIS 知识文本。

    Args:
        ais_query: 已加载的 AISQuery
        output_dir: 输出目录，默认 data/ais_knowledge/
        prefix: doc_name 前缀
        include_anomaly: 是否同时导出异常汇总（需 anomalies 不为空）
        anomalies: detect_by_vessel 返回的 DataFrame
        anomaly_params: 异常检测参数

    Returns:
        {"n_vessels": int, "n_anomaly_files": int, "output_dir": Path}
    """
    from src.config import DATA_DIR

    if output_dir is None:
        output_dir = DATA_DIR / DEFAULT_OUTPUT_DIR_NAME

    n_vessels = export_vessel_knowledge(
        ais_query, output_dir=output_dir, prefix=prefix
    )
    n_anomaly_files = 0
    if include_anomaly and anomalies is not None:
        try:
            import pandas as pd
            has_cols = hasattr(anomalies, "columns") and {
                "vessel_id", "time", "sog", "z_score", "anomaly_type"
            }.issubset(set(anomalies.columns))
            if has_cols and len(anomalies) > 0:
                p = anomaly_params or {"threshold": 2.5, "mode": "by_vessel", "min_n": 5}
                p = export_anomaly_knowledge(
                    ais_query, anomalies, p, output_dir, prefix=prefix
                )
                if p is not None:
                    n_anomaly_files = 1
        except Exception:
            pass

    return {
        "n_vessels": n_vessels,
        "n_anomaly_files": n_anomaly_files,
        "output_dir": output_dir,
    }
