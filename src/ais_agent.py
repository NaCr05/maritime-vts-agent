"""
AIS 自然语言 Agent（基于 LLM Function Calling）

让 LLM 把用户的自然语言问题解析为对 AISQuery / AISLoader 函数的调用，
然后再把函数返回的结构化数据交给 LLM 生成自然语言回答。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import pandas as pd
from openai import OpenAI

from src.ais_loader import AISLoader
from src.ais_query import AISQuery
from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from src.stay_point_detection import detect_anchor_clusters
from src.voyage_segmentation import segment_voyages


SYSTEM_PROMPT = """你是一个 VTS 海事 AIS 数据查询助手，只能基于实际数据集回答。

【核心规则】
1. 凡是涉及数据集/船只/航速/航向/停泊/航程/时间/地点的问题，
   你**必须调用工具**获取真实数据，不要凭知识库或常识编造。
2. 你**只能通过工具获取数据**，你本身不知道任何船只的具体数字。
3. 调用工具后，用工具返回的 JSON 数据用中文自然语言回答用户。
4. 回答时引用具体数字：船只ID、数据点数、平均航速、停泊率、估算航程等。
5. 工具返回空结果/错误时，老实告诉用户"未找到"，不要瞎编。
6. 简明扼要，必要时可用列表展示。

【工具使用指南】
- list_vessels：列出船只概要（最多100条）
- vessel_summary：单船统计（必须有 vessel_id）
- vessels_by_month：按年月筛选活跃船
- vessels_by_area：按经纬度矩形筛选
- vessels_by_time：按时间窗口筛选
- dataset_overview：数据集整体概况（无参数）
- compare_vessels：多船对比（vessel_ids 数组）
- direct_answer：仅当问题**完全不需要数据**（如概念解释、术语定义）时才使用

【严格禁止】
- 禁止不调工具就回答"知识库未找到"——知识库里有 AIS 字段说明文档，不是这个用途。
- 禁止基于常识/猜测说船只数字。
"""


# ============================================================
# 工具定义（OpenAI Function Calling Schema）
# ============================================================
TOOLS_SCHEMA: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_vessels",
            "description": "列出所有船只的概要信息（最多 limit 条）。通常用于'有哪些船'、'数据中有多少船'这类问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "最多返回多少条，默认 20，最多 100",
                        "default": 20,
                        "minimum": 1,
                        "maximum": 100,
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vessel_summary",
            "description": "获取指定渔船 ID 的统计摘要，包括数据点数、平均/最高航速、停泊率、估算航程、地理范围等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "vessel_id": {
                        "type": "integer",
                        "description": "渔船 ID（数字），例如 18330",
                    }
                },
                "required": ["vessel_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vessels_by_month",
            "description": "查询某年某月活跃的船只列表。例如'2020年10月有哪些船'。",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "description": "年份，例如 2020"},
                    "month": {"type": "integer", "description": "月份 1-12"},
                },
                "required": ["year", "month"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vessels_by_area",
            "description": "查询指定地理矩形范围内出现过的船只。坐标单位是度。",
            "parameters": {
                "type": "object",
                "properties": {
                    "lat_min": {"type": "number"},
                    "lat_max": {"type": "number"},
                    "lon_min": {"type": "number"},
                    "lon_max": {"type": "number"},
                },
                "required": ["lat_min", "lat_max", "lon_min", "lon_max"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vessels_by_time",
            "description": "查询指定时间窗口内活跃的船只 ID 列表。时间格式 ISO8601，例如 '2020-10-15 12:00:00'。",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_start": {"type": "string"},
                    "time_end": {"type": "string"},
                },
                "required": ["time_start", "time_end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dataset_overview",
            "description": "获取数据集整体概况：船只总数、轨迹点总数、时间范围、平均航速等。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_vessels",
            "description": "对比多艘船的统计信息（最多 10 艘）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "vessel_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "渔船 ID 列表",
                    }
                },
                "required": ["vessel_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rank_vessels",
            "description": "按航程、航行时长、最高航速、停泊率、轨迹点数或平均航速对船只进行排行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "enum": ["distance", "duration", "max_speed", "stopped_ratio", "points", "avg_speed"],
                        "description": "排序指标：distance=估算航程，duration=航行时长，max_speed=最高航速，stopped_ratio=停泊率，points=轨迹点数，avg_speed=平均航速",
                        "default": "distance",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "返回前多少名，默认 10，最多 50",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stop_points",
            "description": "查询停泊/低速 AIS 点分布，可按船只筛选，并返回样例点和船只停泊点排行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "vessel_id": {"type": "integer", "description": "可选船只 ID"},
                    "threshold": {"type": "number", "description": "低速阈值 kn，默认 0.5", "default": 0.5},
                    "limit": {"type": "integer", "description": "样例点数量，默认 10，最多 50", "default": 10},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_anchor_clusters",
            "description": "基于低速 AIS 点执行 DBSCAN 聚类，识别疑似锚地/停留区。",
            "parameters": {
                "type": "object",
                "properties": {
                    "vessel_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "可选船只 ID 列表；不传则分析全量数据",
                    },
                    "stop_threshold": {"type": "number", "description": "低速阈值 kn，默认 0.5", "default": 0.5},
                    "eps_nm": {"type": "number", "description": "DBSCAN 半径，单位海里，默认 1.0", "default": 1.0},
                    "min_samples": {"type": "integer", "description": "成簇最小点数，默认 20", "default": 20},
                    "top_n": {"type": "integer", "description": "返回前多少个簇，默认 10", "default": 10},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "segment_voyages",
            "description": "按连续低速停泊边界识别指定船只的航次，并返回每段航次的起止时间、航程、航速。",
            "parameters": {
                "type": "object",
                "properties": {
                    "vessel_id": {"type": "integer", "description": "船只 ID"},
                    "stop_threshold": {"type": "number", "description": "低速阈值 kn，默认 0.5", "default": 0.5},
                    "min_stop_hours": {"type": "number", "description": "停泊边界最小时长，默认 3 小时", "default": 3.0},
                    "min_trip_hours": {"type": "number", "description": "最短航次时长，默认 1 小时", "default": 1.0},
                },
                "required": ["vessel_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_monthly_report",
            "description": "生成指定年月的 AIS 月度活动报告文本，包含活跃船只、轨迹点、停泊率、航程排行和最高航速排行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "description": "年份，例如 2020"},
                    "month": {"type": "integer", "description": "月份 1-12"},
                    "top_n": {"type": "integer", "description": "排行返回前多少名，默认 10", "default": 10},
                },
                "required": ["year", "month"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "direct_answer",
            "description": "当用户的问题是纯概念解释、术语定义、方法论咨询，不涉及任何具体船只数据时，使用此工具直接回答。",
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {
                        "type": "string",
                        "description": "对用户问题的直接回答",
                    }
                },
                "required": ["answer"],
            },
        },
    },
]


class AISAgent:
    """基于 Function Calling 的 AIS 自然语言 Agent。"""

    def __init__(self, ais_query: AISQuery, ais_loader: AISLoader):
        self.ais_query = ais_query
        self.ais_loader = ais_loader
        self._client: Optional[OpenAI] = None

    @staticmethod
    def is_llm_available() -> bool:
        return bool(LLM_API_KEY)

    def has_llm(self) -> bool:
        """实例方法版本。"""
        return self.is_llm_available()

    def _build_client(self) -> Optional[OpenAI]:
        if not LLM_API_KEY:
            return None
        if self._client is None:
            kwargs = {"api_key": LLM_API_KEY}
            if LLM_BASE_URL:
                kwargs["base_url"] = LLM_BASE_URL
            self._client = OpenAI(**kwargs)
        return self._client

    # --------------------------------------------------------
    # 工具实际执行
    # --------------------------------------------------------
    def _execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if name == "list_vessels":
                limit = int(arguments.get("limit", 20))
                return {
                    "vessels": self.ais_loader.registry[:limit],
                    "total_vessels": len(self.ais_loader.registry),
                    "returned": min(limit, len(self.ais_loader.registry)),
                }

            if name == "vessel_summary":
                vid = int(arguments["vessel_id"])
                summary = self.ais_query.vessel_summary(vid)
                if not summary:
                    return {"error": f"未找到渔船 {vid} 的数据"}
                return summary

            if name == "vessels_by_month":
                year = int(arguments["year"])
                month = int(arguments["month"])
                vessels = self.ais_loader.get_vessels_by_month(year, month)
                return {
                    "year": year,
                    "month": month,
                    "n_vessels": len(vessels),
                    "vessels": vessels,
                }

            if name == "vessels_by_area":
                lat_min = float(arguments["lat_min"])
                lat_max = float(arguments["lat_max"])
                lon_min = float(arguments["lon_min"])
                lon_max = float(arguments["lon_max"])
                ids = self.ais_loader.get_vessels_by_area(
                    lat_min, lat_max, lon_min, lon_max
                )
                return {
                    "bbox": {
                        "lat_min": lat_min, "lat_max": lat_max,
                        "lon_min": lon_min, "lon_max": lon_max,
                    },
                    "n_vessels": len(ids),
                    "vessel_ids": ids,
                }

            if name == "vessels_by_time":
                ts = pd.Timestamp(arguments["time_start"])
                te = pd.Timestamp(arguments["time_end"])
                ids = self.ais_loader.get_vessels_by_time(ts, te)
                return {
                    "time_start": str(ts),
                    "time_end": str(te),
                    "n_vessels": len(ids),
                    "vessel_ids": ids,
                }

            if name == "dataset_overview":
                df = self.ais_query.df
                registry = self.ais_loader.registry
                return {
                    "total_vessels": len(registry),
                    "total_points": int(len(df)),
                    "time_start": str(df["time"].min()),
                    "time_end": str(df["time"].max()),
                    "sog_overall_mean": round(float(df["sog"].mean()), 2),
                    "sog_overall_max": round(float(df["sog"].max()), 2),
                    "sog_overall_min": round(float(df["sog"].min()), 2),
                    "stopped_ratio_pct": round(
                        float((df["sog"] < 0.5).sum() / len(df) * 100), 1
                    ),
                    "vessel_id_range": [
                        int(df["vessel_id"].min()),
                        int(df["vessel_id"].max()),
                    ],
                }

            if name == "compare_vessels":
                ids = [int(x) for x in arguments["vessel_ids"][:10]]
                return {"comparison": self.ais_query.multi_vessel_comparison(ids)}

            if name == "rank_vessels":
                metric = arguments.get("metric", "distance")
                top_n = max(1, min(int(arguments.get("top_n", 10)), 50))
                metric_map = {
                    "distance": ("total_distance_nm", "估算航程(nm)"),
                    "duration": ("duration_hours", "航行时长(h)"),
                    "max_speed": ("sog_max", "最高航速(kn)"),
                    "stopped_ratio": ("stopped_ratio_pct", "停泊率(%)"),
                    "points": ("n_points", "轨迹点数"),
                    "avg_speed": ("sog_mean", "平均航速(kn)"),
                }
                sort_key, metric_label = metric_map.get(metric, metric_map["distance"])
                rows = []
                for meta in self.ais_loader.registry:
                    summary = self.ais_query.vessel_summary(int(meta["vessel_id"]))
                    if not summary:
                        continue
                    rows.append({
                        "vessel_id": int(summary["vessel_id"]),
                        "metric": float(summary[sort_key]),
                        "metric_label": metric_label,
                        "total_distance_nm": summary["total_distance_nm"],
                        "duration_hours": summary["duration_hours"],
                        "sog_mean": summary["sog_mean"],
                        "sog_max": summary["sog_max"],
                        "stopped_ratio_pct": summary["stopped_ratio_pct"],
                        "n_points": summary["n_points"],
                    })
                rows = sorted(rows, key=lambda r: r["metric"], reverse=True)[:top_n]
                for idx, row in enumerate(rows, start=1):
                    row["rank"] = idx
                return {
                    "metric": metric,
                    "metric_label": metric_label,
                    "top_n": top_n,
                    "ranking": rows,
                }

            if name == "get_stop_points":
                threshold = float(arguments.get("threshold", 0.5))
                limit = max(1, min(int(arguments.get("limit", 10)), 50))
                df = self.ais_query.df
                if "vessel_id" in arguments and arguments["vessel_id"] is not None:
                    vid = int(arguments["vessel_id"])
                    df = df[df["vessel_id"] == vid]
                stop_df = df[df["sog"] < threshold].copy()
                sample_cols = ["vessel_id", "time", "lat", "lon", "sog", "cog"]
                sample = stop_df.sort_values("time").head(limit)[sample_cols].copy()
                if len(sample) > 0:
                    sample["time"] = pd.to_datetime(sample["time"]).dt.strftime("%Y-%m-%d %H:%M")
                vessel_counts = []
                if len(stop_df) > 0:
                    vessel_counts = (
                        stop_df.groupby("vessel_id")
                        .size()
                        .sort_values(ascending=False)
                        .head(10)
                        .reset_index(name="stop_points")
                        .to_dict(orient="records")
                    )
                return {
                    "threshold": threshold,
                    "total_stop_points": int(len(stop_df)),
                    "total_scope_points": int(len(df)),
                    "n_vessels": int(stop_df["vessel_id"].nunique()) if len(stop_df) else 0,
                    "top_vessels_by_stop_points": vessel_counts,
                    "sample_points": sample.to_dict(orient="records"),
                }

            if name == "detect_anchor_clusters":
                df = self.ais_query.df
                vessel_ids = arguments.get("vessel_ids") or []
                if vessel_ids:
                    ids = [int(x) for x in vessel_ids[:20]]
                    df = df[df["vessel_id"].isin(ids)]
                stop_threshold = float(arguments.get("stop_threshold", 0.5))
                eps_nm = float(arguments.get("eps_nm", 1.0))
                min_samples = int(arguments.get("min_samples", 20))
                top_n = max(1, min(int(arguments.get("top_n", 10)), 30))
                clusters, clustered_points = detect_anchor_clusters(
                    df,
                    stop_threshold=stop_threshold,
                    eps_nm=eps_nm,
                    min_samples=min_samples,
                )
                return {
                    "parameters": {
                        "stop_threshold": stop_threshold,
                        "eps_nm": eps_nm,
                        "min_samples": min_samples,
                    },
                    "n_clusters": int(len(clusters)),
                    "n_low_speed_points": int(len(clustered_points)),
                    "n_noise_points": int((clustered_points["cluster_id"] == -1).sum()) if len(clustered_points) else 0,
                    "clusters": clusters.head(top_n).to_dict(orient="records"),
                }

            if name == "segment_voyages":
                vid = int(arguments["vessel_id"])
                traj = self.ais_query.get_trajectory(vid)
                if len(traj) == 0:
                    return {"error": f"未找到渔船 {vid} 的数据"}
                voyages = segment_voyages(
                    traj,
                    stop_threshold=float(arguments.get("stop_threshold", 0.5)),
                    min_stop_hours=float(arguments.get("min_stop_hours", 3.0)),
                    min_trip_hours=float(arguments.get("min_trip_hours", 1.0)),
                )
                return {
                    "vessel_id": vid,
                    "n_voyages": int(len(voyages)),
                    "total_distance_nm": round(float(voyages["distance_nm"].sum()), 1) if len(voyages) else 0.0,
                    "total_duration_h": round(float(voyages["duration_h"].sum()), 1) if len(voyages) else 0.0,
                    "voyages": voyages.head(20).to_dict(orient="records"),
                }

            if name == "generate_monthly_report":
                year = int(arguments["year"])
                month = int(arguments["month"])
                top_n = max(1, min(int(arguments.get("top_n", 10)), 20))
                month_start = pd.Timestamp(year=year, month=month, day=1)
                month_end = month_start + pd.DateOffset(months=1)
                df = self.ais_query.df[
                    (self.ais_query.df["time"] >= month_start)
                    & (self.ais_query.df["time"] < month_end)
                ].copy()
                if len(df) == 0:
                    return {"error": f"{year}-{month:02d} 没有 AIS 数据"}

                rows = []
                for vid, vdf in df.groupby("vessel_id"):
                    rows.append({
                        "vessel_id": int(vid),
                        "n_points": int(len(vdf)),
                        "duration_hours": round((vdf["time"].max() - vdf["time"].min()).total_seconds() / 3600, 1),
                        "total_distance_nm": round(AISQuery._calc_total_distance(vdf.sort_values("time")), 1),
                        "sog_mean": round(float(vdf["sog"].mean()), 1),
                        "sog_max": round(float(vdf["sog"].max()), 1),
                        "stopped_ratio_pct": round(float((vdf["sog"] < 0.5).sum() / len(vdf) * 100), 1),
                    })
                rank_df = pd.DataFrame(rows)
                top_distance = rank_df.sort_values("total_distance_nm", ascending=False).head(top_n)
                top_speed = rank_df.sort_values("sog_max", ascending=False).head(top_n)
                report = [
                    f"# VTS 月度 AIS 活动报告（{year}-{month:02d}）",
                    f"- 活跃船只数：{df['vessel_id'].nunique()} 艘",
                    f"- AIS 轨迹点数：{len(df):,} 个",
                    f"- 记录时间范围：{df['time'].min()} 至 {df['time'].max()}",
                    f"- 平均航速：{float(df['sog'].mean()):.1f} kn",
                    f"- 最高航速：{float(df['sog'].max()):.1f} kn",
                    f"- 停泊点占比：{float((df['sog'] < 0.5).sum() / len(df) * 100):.1f}%",
                    "",
                    f"## 估算航程 Top {top_n}",
                ]
                for idx, row in enumerate(top_distance.to_dict(orient="records"), start=1):
                    report.append(
                        f"{idx}. 船 {int(row['vessel_id'])}：{row['total_distance_nm']} nm，"
                        f"活跃 {row['duration_hours']} h，停泊率 {row['stopped_ratio_pct']}%"
                    )
                report.extend(["", f"## 最高航速 Top {top_n}"])
                for idx, row in enumerate(top_speed.to_dict(orient="records"), start=1):
                    report.append(
                        f"{idx}. 船 {int(row['vessel_id'])}：最高 {row['sog_max']} kn，"
                        f"平均 {row['sog_mean']} kn"
                    )
                return {
                    "year": year,
                    "month": month,
                    "report_text": "\n".join(report),
                    "top_distance": top_distance.to_dict(orient="records"),
                    "top_speed": top_speed.to_dict(orient="records"),
                }

            if name == "direct_answer":
                # 这是一个“放行”工具：让 LLM 在不需要数据时合法地直接答
                return {"direct": True, "answer": arguments.get("answer", "")}

            return {"error": f"未知工具: {name}"}
        except Exception as e:
            return {"error": f"工具 {name} 执行失败: {e}"}

    # --------------------------------------------------------
    # 主入口
    # --------------------------------------------------------
    def ask(
        self,
        question: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        处理用户的自然语言 AIS 查询。

        返回结构：
            {
              "answer": str,
              "tool_calls": [{"name", "arguments", "result"}, ...],
              "available": bool,   # LLM 是否可用
            }
        """
        client = self._build_client()
        if client is None:
            return {
                "answer": (
                    "当前未配置 LLM_API_KEY，无法使用 AI 智能查询。\n\n"
                    "请在项目根目录的 .env 文件中配置 DEEPSEEK_API_KEY，"
                    "重启 demo 后即可启用自然语言 AIS 查询。"
                ),
                "tool_calls": [],
                "available": False,
            }

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        if chat_history:
            messages.extend(chat_history)
        messages.append({"role": "user", "content": question})

        tool_calls_log: List[Dict[str, Any]] = []
        max_iterations = 5
        forced_retry = False

        for iteration in range(max_iterations):
            try:
                response = client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=messages,
                    tools=TOOLS_SCHEMA,
                    tool_choice="auto",
                    temperature=0.1,
                )
            except Exception as e:
                return {
                    "answer": f"⚠️ LLM 调用失败：{e}",
                    "tool_calls": tool_calls_log,
                    "available": True,
                }

            msg = response.choices[0].message

            # 如果 LLM 想调用工具
            if msg.tool_calls:
                # 把助手消息加入历史（注意要带 tool_calls）
                messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                })

                # 依次执行每个工具调用
                direct_answer_text = None
                for tc in msg.tool_calls:
                    fn_name = tc.function.name
                    try:
                        fn_args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        fn_args = {}

                    result = self._execute_tool(fn_name, fn_args)
                    tool_calls_log.append({
                        "name": fn_name,
                        "arguments": fn_args,
                        "result": result,
                    })

                    # 如果是 direct_answer 工具，立即返回
                    if isinstance(result, dict) and result.get("direct"):
                        direct_answer_text = result.get("answer", "")

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": fn_name,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })

                # 如果 LLM 主动选了 direct_answer，跳出循环直接返回
                if direct_answer_text is not None:
                    return {
                        "answer": direct_answer_text,
                        "tool_calls": tool_calls_log,
                        "available": True,
                    }

                # 继续循环，让 LLM 基于工具结果生成最终答案
                continue

            # 如果 LLM 没调工具 — 这是退化情况，需要强制重试一次
            if not forced_retry and iteration == 0:
                forced_retry = True
                # 把 LLM 的"乱答"作为助手消息放进历史
                if msg.content:
                    messages.append({"role": "assistant", "content": msg.content})
                # 强制追加 user 提示
                messages.append({
                    "role": "user",
                    "content": (
                        "⚠️ 你的上一轮回答没有调用任何工具。"
                        "请重新检查你的工具列表：这个问题涉及 AIS 数据，"
                        "必须调用一个数据查询工具（如 dataset_overview、vessel_summary、"
                        "vessels_by_month、list_vessels 等），"
                        "或者如果只是概念解释就调用 direct_answer 工具。"
                        "再次调用工具给出真实数据。"
                    )
                })
                continue

            # 已经强制重试过了 — 这是 LLM 实在不肯调工具的兜底
            fallback_text = msg.content or "（模型未返回内容）"
            # 如果连 fallback 都说"知识库未找到"，那换成更明确的提示
            if "知识库" in fallback_text and "未找到" in fallback_text:
                fallback_text = (
                    "AI 在第二轮仍然没调用数据查询工具，"
                    "无法给出真实数据。请换个更具体的问法，"
                    "或直接告诉我船 ID / 年月 / 地理范围。"
                )
            return {
                "answer": fallback_text,
                "tool_calls": tool_calls_log,
                "available": True,
            }

        # 超过最大轮次
        return {
            "answer": "⚠️ 工具调用轮次过多，已中止。请简化你的问题。",
            "tool_calls": tool_calls_log,
            "available": True,
        }
