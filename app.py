import os
os.environ["TQDM_DISABLE"] = "1"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import sys as _sys
import types as _types
import importlib as _importlib

class _NoOpTqdm:
    def __init__(self, iterable=None, *a, **kw):
        self.iterable = iterable
        self.total = kw.get("total")
        self.n = 0
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def update(self, *a): pass
    def set_description(self, *a, **kw): pass
    def set_postfix(self, *a, **kw): pass
    def write(self, *a, **kw): pass
    def close(self): pass
    def __iter__(self):
        if self.iterable is None:
            return iter(())
        return iter(self.iterable)
    def __len__(self):
        if self.iterable is not None:
            try:
                return len(self.iterable)
            except TypeError:
                pass
        return int(self.total or 0)
    @staticmethod
    def set_lock(*a): pass
    @staticmethod
    def get_lock(): return None
    @staticmethod
    def reset_lock(): pass

class _FakeSpec:
    def __init__(self, name):
        self.name = name
        self.origin = None
        self.submodule_search_locations = []
        self.parent = name.rsplit('.', 1)[0] if '.' in name else ''

class _FakeLoader:
    @staticmethod
    def find_spec(fullname, path=None, target=None):
        if fullname in __import__('sys').modules:
            return __import__('importlib').util.find_spec(fullname)
        return None
    def create_module(self, spec): return None
    def exec_module(self, module): pass
    @staticmethod
    def find_module(fullname, path=None):
        if fullname in __import__('sys').modules:
            return _FakeLoader()
        return None

class _AutoModule(_types.ModuleType):
    def __init__(self, name):
        super().__init__(name)
        self.__path__ = []
    def __getattr__(self, attr):
        if attr.startswith('_'):
            raise AttributeError(attr)
        child_name = f"{self.__name__}.{attr}"
        child = type(self)(child_name)
        __import__('sys').modules[child_name] = child
        setattr(self, attr, child)
        return child
    def load_module(self, fullname):
        return __import__('sys').modules.get(fullname)

_fake_tqdm = _AutoModule("tqdm")
_fake_tqdm.tqdm = _NoOpTqdm
_fake_tqdm.auto = _fake_tqdm
_fake_tqdm.std = _fake_tqdm
_fake_tqdm.trange = lambda *a, **kw: _NoOpTqdm(range(*a), **kw)
_fake_tqdm.set_lock = staticmethod(lambda *a: None)
_fake_tqdm.get_lock = staticmethod(lambda: None)
_fake_tqdm.reset_lock = staticmethod(lambda *a: None)
_fake_tqdm.__path__ = []
_fake_tqdm.__file__ = "<fake_tqdm>"
_fake_tqdm.__package__ = "tqdm"
_fake_tqdm.__spec__ = _FakeSpec("tqdm")
_fake_tqdm.__loader__ = _FakeLoader()

_contrib = _AutoModule("tqdm.contrib")
_contrib.__path__ = []
_contrib.__file__ = "<fake_tqdm.contrib>"
_contrib.__package__ = "tqdm.contrib"
_contrib.__spec__ = _FakeSpec("tqdm.contrib")
_contrib.__loader__ = _FakeLoader()

_contrib_concurrent = _AutoModule("tqdm.contrib.concurrent")
_contrib_concurrent.__path__ = []
_contrib_concurrent.__file__ = "<fake_tqdm.contrib.concurrent>"
_contrib_concurrent.__package__ = "tqdm.contrib.concurrent"
_contrib_concurrent.__spec__ = _FakeSpec("tqdm.contrib.concurrent")
_contrib_concurrent.__loader__ = _FakeLoader()
_contrib_concurrent.thread_map = lambda fn, *iterables, **kw: list(map(fn, *iterables))
setattr(_contrib, "concurrent", _contrib_concurrent)

_contrib_logging = _AutoModule("tqdm.contrib.logging")
_contrib_logging.__path__ = []
_contrib_logging.__file__ = "<fake_tqdm.contrib.logging>"
_contrib_logging.__package__ = "tqdm.contrib.logging"
_contrib_logging.__spec__ = _FakeSpec("tqdm.contrib.logging")
_contrib_logging.__loader__ = _FakeLoader()
setattr(_contrib, "logging", _contrib_logging)

_autonotebook = _AutoModule("tqdm.autonotebook")
_autonotebook.__path__ = []
_autonotebook.__file__ = "<fake_tqdm.autonotebook>"
_autonotebook.__package__ = "tqdm.autonotebook"
_autonotebook.__spec__ = _FakeSpec("tqdm.autonotebook")
_autonotebook.__loader__ = _FakeLoader()
_autonotebook.tqdm = _NoOpTqdm
_autonotebook.trange = lambda *a, **kw: _NoOpTqdm(range(*a), **kw)
setattr(_fake_tqdm, "autonotebook", _autonotebook)

_sys.modules["tqdm"] = _fake_tqdm
_sys.modules["tqdm.auto"] = _fake_tqdm
_sys.modules["tqdm.std"] = _fake_tqdm
_sys.modules["tqdm.contrib"] = _contrib
_sys.modules["tqdm.contrib.concurrent"] = _contrib_concurrent
_sys.modules["tqdm.contrib.logging"] = _contrib_logging
_sys.modules["tqdm.autonotebook"] = _autonotebook

del _sys, _types, _importlib
del _NoOpTqdm, _FakeSpec, _FakeLoader  # keep _AutoModule for __getattr__ references
del _fake_tqdm, _contrib, _contrib_concurrent, _contrib_logging, _autonotebook

import sys

# 替换 sys.stderr 的 write/flush 方法，防止 tqdm 在 Windows 中文路径下崩溃
# OSError: [Errno 22] 源于 Streamlit 把 stderr 重定向到含中文路径的文件句柄
_real_stderr = sys.stderr
_safe_guard = False  # 防止递归

def _safe_stderr_write(s):
    global _safe_guard
    if _safe_guard:
        return
    try:
        _safe_guard = True
        _real_stderr.write(s)
    except (OSError, ValueError, TypeError):
        pass
    finally:
        _safe_guard = False

def _safe_stderr_flush():
    global _safe_guard
    if _safe_guard:
        return
    try:
        _safe_guard = True
        _real_stderr.flush()
    except (OSError, ValueError):
        pass
    finally:
        _safe_guard = False

sys.stderr.write = _safe_stderr_write
sys.stderr.flush = _safe_stderr_flush

import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
import traceback
import weakref

# 在 Streamlit 完全加载后，patch tqdm 以防止 fp_write 崩溃
try:
    import tqdm
    _orig_tqdm_display = tqdm.tqdm.display
    def _safe_tqdm_display(self, *a, **kw):
        try:
            return _orig_tqdm_display(self, *a, **kw)
        except Exception:
            pass
    tqdm.tqdm.display = _safe_tqdm_display
    # 也 patch auto 包装器
    if hasattr(tqdm, 'auto'):
        tqdm.auto.tqdm.display = _safe_tqdm_display
except Exception:
    pass

# 调试日志函数（用于追踪卡住的位置）
_debug_file = os.path.join(os.path.dirname(__file__), ".debug_main.log")
def _log(msg):
    try:
        with open(_debug_file, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _prepare_layer_data(layer):
    """将 layer.data 中的 DataFrame 转换为纯 list[dict]，兼容 pandas 3.x。"""
    import pandas as pd
    data = getattr(layer, 'data', None)
    if data is None:
        return
    if isinstance(data, weakref.ref):
        data = data()
        if data is None:
            return
    if isinstance(data, pd.DataFrame):
        layer.data = data.to_dict(orient='records')


def _safe_deck(*args, **kwargs):
    """创建 pdk.Deck 后，自动转换所有 layer.data 中的 DataFrame。"""
    deck = pdk.Deck(*args, **kwargs)
    for layer in getattr(deck, 'layers', []) or []:
        _prepare_layer_data(layer)
    return deck


try:
    from src.config import DATA_DIR, EMBEDDING_MODEL, AIS_KNOWLEDGE_DIR, RESTRICTED_ZONES
    _config_load_ok = True
except ImportError as e:
    # fallback：兼容旧版 config.py（无 AIS_KNOWLEDGE_DIR 时使用内联路径）
    import os
    from src.config import DATA_DIR, EMBEDDING_MODEL
    AIS_KNOWLEDGE_DIR = DATA_DIR / "ais_knowledge"
    _config_load_ok = False
    # RESTRICTED_ZONES fallback：内联定义预定义区域
    RESTRICTED_ZONES = [
        {
            "name": "长江口核心区",
            "type": "rect",
            "lat_min": 30.80,
            "lat_max": 31.20,
            "lon_min": 121.80,
            "lon_max": 122.20,
            "description": "长江入海口核心管控水域",
        },
        {
            "name": "舟山港口",
            "type": "rect",
            "lat_min": 29.80,
            "lat_max": 30.30,
            "lon_min": 121.60,
            "lon_max": 122.30,
            "description": "浙江舟山群岛主要港口水域",
        },
        {
            "name": "军事演习区 A",
            "type": "circle",
            "lat": 30.50,
            "lon": 122.50,
            "radius_nm": 10.0,
            "description": "军事演习禁航区域（示例）",
        },
        {
            "name": "嵊泗渔场保护区",
            "type": "circle",
            "lat": 30.80,
            "lon": 122.30,
            "radius_nm": 8.0,
            "description": "重要渔业资源保护区（示例）",
        },
    ]
    import warnings
    warnings.warn(f"[config] RESTRICTED_ZONES fallback used (config import failed: {e})")
from src.geo_fence import check_all_zones, get_violation_trajectory_segments, summarize_violations
from src.document_loader import build_chunks
import importlib as _runtime_importlib
import src.rag_engine as _rag_engine_module
_rag_engine_module = _runtime_importlib.reload(_rag_engine_module)
RAGEngine = _rag_engine_module.RAGEngine
from src.risk_tools import judge_vessel_risk
from src.ais_loader import AISLoader
from src.ais_query import AISQuery
from src.ais_agent import AISAgent
from src.ais_knowledge_exporter import export_all_ais_knowledge
from src.speed_anomaly import detect_by_vessel, detect_global, summarize_anomalies
from src.stay_point_detection import detect_anchor_clusters, summarize_anchor_clusters
from src.voyage_segmentation import segment_voyages_for_ids, summarize_voyages
from src.report_exporter import markdown_to_docx_bytes, markdown_to_pdf_bytes
from ui.ais_analysis_page import render_ais_analysis_nav
from ui.rag_page import render_rag_page
from ui.report_page import render_monthly_report_page
from ui.fence_page import render_fence_page


st.set_page_config(
    page_title="Maritime VTS Knowledge Agent",
    page_icon="⚓",
    layout="wide"
)


def _fallback_load_ais_chunks(extra_dirs):
    """不依赖 document_loader 任何版本，直接读 AIS .txt。
    兼容 Streamlit 进程缓存了旧版 document_loader（无 prefix / extra_dirs）的场景。
    """
    import re
    chunks = []
    for extra_path, prefix in extra_dirs:
        if not extra_path.exists() or not extra_path.is_dir():
            continue
        for f in sorted(extra_path.glob("*.txt")):
            try:
                text = f.read_text(encoding="utf-8").strip()
            except Exception:
                continue
            if not text:
                continue
            doc_name = f"{prefix}{f.name}" if prefix else f.name
            source_type = (
                "ais_knowledge" if doc_name.startswith("ais_knowledge/")
                else "maritime_doc"
            )
            # 复用 document_loader.split_text 的字符切分策略（chunk_size=450, overlap=80）
            start = 0
            idx = 0
            while start < len(text):
                end = start + 450
                chunk_text = text[start:end].strip()
                if chunk_text:
                    chunks.append(
                        _make_chunk(
                            doc_name=doc_name,
                            chunk_id=idx,
                            text=chunk_text,
                            source_type=source_type,
                        )
                    )
                    idx += 1
                start = end - 80
                if start < 0:
                    start = 0
                if start >= len(text):
                    break
    return chunks


def _make_chunk(doc_name, chunk_id, text, source_type):
    """构造 DocumentChunk，兼容任何版本（带 / 不带 source_type 字段）。"""
    try:
        from src.document_loader import DocumentChunk
        try:
            return DocumentChunk(
                doc_name=doc_name,
                chunk_id=chunk_id,
                text=text,
                source_type=source_type,
            )
        except TypeError:
            return DocumentChunk(doc_name=doc_name, chunk_id=chunk_id, text=text)
    except Exception:
        # 极端 fallback：用 dataclass 的最小子集，足够给 vector_store 用
        class _MiniChunk:
            pass
        c = _MiniChunk()
        c.doc_name = doc_name
        c.chunk_id = chunk_id
        c.text = text
        c.source_type = source_type
        return c


@st.cache_resource(show_spinner=False)
def load_vector_store():
    _log(">>> LVS step 1: import SimpleVectorStore")
    import src.vector_store as _vector_store_module
    _vector_store_module = _runtime_importlib.reload(_vector_store_module)
    _SVS = _vector_store_module.SimpleVectorStore
    _log(">>> LVS step 2: SimpleVectorStore imported OK")

    extra_dirs = []
    if AIS_KNOWLEDGE_DIR.exists() and AIS_KNOWLEDGE_DIR.is_dir():
        extra_dirs.append((AIS_KNOWLEDGE_DIR, "ais_knowledge/"))

    # 优先用 build_chunks（任何签名都试）
    chunks = None
    for call in (
        lambda: build_chunks(DATA_DIR, extra_dirs=extra_dirs if extra_dirs else None),
        lambda: build_chunks(DATA_DIR),
    ):
        try:
            chunks = call()
            break
        except TypeError:
            continue

    if chunks is None:
        # 终极 fallback：手动读主目录
        chunks = []
        if DATA_DIR.exists():
            for f in DATA_DIR.glob("*.txt"):
                try:
                    text = f.read_text(encoding="utf-8").strip()
                except Exception:
                    continue
                if not text:
                    continue
                chunks.append(
                    _make_chunk(
                        doc_name=f.name,
                        chunk_id=0,
                        text=text,
                        source_type="maritime_doc",
                    )
                )

    # 仅在旧版 build_chunks 不支持 extra_dirs 时补读 AIS 文件，避免重复加载。
    has_ais_chunks = any(
        getattr(chunk, "doc_name", "").startswith("ais_knowledge/")
        for chunk in chunks
    )
    if extra_dirs and not has_ais_chunks:
        chunks.extend(_fallback_load_ais_chunks(extra_dirs))

    _log(f">>> LVS step 5: about to instantiate SimpleVectorStore(model={EMBEDDING_MODEL})")
    vector_store = _SVS(model_name=EMBEDDING_MODEL)
    _log(">>> LVS step 6: SimpleVectorStore instantiated, building chunks")
    vector_store.build(chunks)
    _log(f">>> LVS step 7: build done, {len(vector_store.chunks)} chunks")
    return vector_store


@st.cache_resource(show_spinner=False)
def load_ais():
    loader = AISLoader()
    query = AISQuery(loader)
    query.load()
    return loader, query


def render_sources(sources, retrieval_mode="rag", max_preview_chars=200):
    """
    渲染知识库检索片段。

    Args:
        sources: 检索片段列表
        retrieval_mode: "rag" = 知识库 RAG 路径, "general" = 大模型通用知识路径
    """
    # 路径标签
    if retrieval_mode == "rag":
        st.success("✅ 知识库检索路径 — 已找到相关片段", icon="📚")
    else:
        st.info("🌐 大模型通用知识路径 — 知识库未找到相关内容，已由 AI 自主回答", icon="🤖")

    if not sources:
        return

    def _source_label(source_type: str) -> str:
        if source_type == "ais_knowledge":
            return "📡 AIS 知识库"
        return "📄 海事文档"

    with st.expander(
        f"查看检索到的知识库片段（共 {len(sources)} 条）",
        expanded=False
    ):
        with st.container(height=350):
            for idx, source in enumerate(sources, start=1):
                label = _source_label(source.get("source_type", "maritime_doc"))
                st.markdown(
                    f"**片段 {idx}** {label} | 来源：`{source['doc_name']}` | "
                    f"chunk_id：`{source['chunk_id']}` | "
                    f"相似度：`{source['score']}` | 长度：`{len(source['text'])}` 字符"
                )
                text = source["text"]
                if len(text) > max_preview_chars:
                    st.text(text[:max_preview_chars] + " ...[已截断，完整内容见知识库文件]")
                else:
                    st.text(text)
                st.divider()


def vessel_stat_card(label: str, value, unit: str = ""):
    st.metric(label, f"{value}{unit}" if unit else value)


def _calc_monthly_vessel_rows(month_df: pd.DataFrame, ais_query: AISQuery) -> pd.DataFrame:
    rows = []
    if month_df is None or len(month_df) == 0:
        return pd.DataFrame()

    for vid, vdf in month_df.groupby("vessel_id"):
        vdf = vdf.sort_values("time")
        duration_h = (vdf["time"].max() - vdf["time"].min()).total_seconds() / 3600
        rows.append({
            "船 ID": int(vid),
            "轨迹点数": int(len(vdf)),
            "开始时间": pd.Timestamp(vdf["time"].min()).strftime("%Y-%m-%d %H:%M"),
            "结束时间": pd.Timestamp(vdf["time"].max()).strftime("%Y-%m-%d %H:%M"),
            "活跃时长(h)": round(duration_h, 1),
            "估算航程(nm)": round(ais_query._calc_total_distance(vdf), 1),
            "平均航速(kn)": round(float(vdf["sog"].mean()), 1),
            "最高航速(kn)": round(float(vdf["sog"].max()), 1),
            "停泊率(%)": round(float((vdf["sog"] < 0.5).sum() / len(vdf) * 100), 1),
        })

    return pd.DataFrame(rows)


def _markdown_table(df: pd.DataFrame, columns: list[str], max_rows: int = 10) -> str:
    if df is None or len(df) == 0:
        return "无数据。\n"
    view = df[columns].head(max_rows).copy()
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join(["---"] * len(columns)) + " |"
    rows = []
    for _, row in view.iterrows():
        values = []
        for col in columns:
            val = row[col]
            if isinstance(val, float):
                values.append(f"{val:.1f}")
            else:
                values.append(str(val))
        rows.append("| " + " | ".join(values) + " |")
    return "\n".join([header, divider] + rows)


def build_monthly_report_text(
    year: int,
    month: int,
    month_df: pd.DataFrame,
    monthly_vessels: pd.DataFrame,
    anomalies: pd.DataFrame | None,
    violations: pd.DataFrame | None,
    top_n: int = 10,
) -> str:
    month_label = f"{year}-{month:02d}"
    total_points = len(month_df)
    n_vessels = month_df["vessel_id"].nunique() if total_points else 0
    avg_sog = float(month_df["sog"].mean()) if total_points else 0.0
    max_sog = float(month_df["sog"].max()) if total_points else 0.0
    stop_ratio = float((month_df["sog"] < 0.5).sum() / total_points * 100) if total_points else 0.0
    time_start = pd.Timestamp(month_df["time"].min()).strftime("%Y-%m-%d %H:%M") if total_points else "-"
    time_end = pd.Timestamp(month_df["time"].max()).strftime("%Y-%m-%d %H:%M") if total_points else "-"

    top_distance = monthly_vessels.sort_values("估算航程(nm)", ascending=False)
    top_duration = monthly_vessels.sort_values("活跃时长(h)", ascending=False)
    top_stop = monthly_vessels.sort_values("停泊率(%)", ascending=False)
    top_speed = monthly_vessels.sort_values("最高航速(kn)", ascending=False)

    anomaly_count = 0 if anomalies is None else len(anomalies)
    anomaly_vessels = 0 if anomalies is None or len(anomalies) == 0 else anomalies["vessel_id"].nunique()
    violation_count = 0 if violations is None else len(violations)
    violation_vessels = 0 if violations is None or len(violations) == 0 else violations["vessel_id"].nunique()

    lines = [
        f"# VTS 月度 AIS 活动报告（{month_label}）",
        "",
        "## 1. 基本概况",
        f"- 报告月份：{month_label}",
        f"- 活跃船只数：{n_vessels} 艘",
        f"- AIS 轨迹点数：{total_points:,} 个",
        f"- 记录时间范围：{time_start} 至 {time_end}",
        f"- 平均航速：{avg_sog:.1f} kn",
        f"- 最高航速：{max_sog:.1f} kn",
        f"- 低速/停泊点占比（SOG < 0.5 kn）：{stop_ratio:.1f}%",
        "",
        "## 2. 活跃船只排行",
        "",
        f"### 2.1 估算航程 Top {top_n}",
        _markdown_table(top_distance, ["船 ID", "估算航程(nm)", "活跃时长(h)", "平均航速(kn)", "停泊率(%)"], max_rows=top_n),
        "",
        f"### 2.2 活跃时长 Top {top_n}",
        _markdown_table(top_duration, ["船 ID", "活跃时长(h)", "估算航程(nm)", "轨迹点数", "停泊率(%)"], max_rows=top_n),
        "",
        f"### 2.3 停泊率 Top {top_n}",
        _markdown_table(top_stop, ["船 ID", "停泊率(%)", "轨迹点数", "估算航程(nm)", "最高航速(kn)"], max_rows=top_n),
        "",
        f"### 2.4 最高航速 Top {top_n}",
        _markdown_table(top_speed, ["船 ID", "最高航速(kn)", "平均航速(kn)", "估算航程(nm)", "停泊率(%)"], max_rows=top_n),
        "",
        "## 3. 航速异常事件",
    ]

    if anomalies is None:
        lines.append("本次报告未启用航速异常检测。")
    elif len(anomalies) == 0:
        lines.append("未发现航速异常。")
    else:
        anomaly_view = anomalies.sort_values("z_score", key=lambda s: s.abs(), ascending=False).head(10).copy()
        anomaly_view["time"] = pd.to_datetime(anomaly_view["time"]).dt.strftime("%Y-%m-%d %H:%M")
        lines.extend([
            f"- 异常记录总数：{anomaly_count} 条",
            f"- 涉及船只：{anomaly_vessels} 艘",
            "",
            _markdown_table(
                anomaly_view.rename(columns={
                    "vessel_id": "船 ID",
                    "time": "时间",
                    "sog": "航速(kn)",
                    "z_score": "Z-Score",
                    "anomaly_type": "异常类型",
                }),
                ["船 ID", "时间", "航速(kn)", "Z-Score", "异常类型"],
                max_rows=top_n,
            ),
        ])

    lines.extend(["", "## 4. 禁航区 / 围栏风险"])
    if violations is None:
        lines.append("本次报告未启用地理围栏检测。")
    elif len(violations) == 0:
        lines.append("未发现进入禁航区的记录。")
    else:
        violation_view = violations[[
            "vessel_id", "zone_name", "zone_type", "first_entry", "duration_h", "n_entries", "n_points"
        ]].copy()
        violation_view.columns = ["船 ID", "区域", "类型", "首次进入", "滞留时长(h)", "进入次数", "轨迹点数"]
        lines.extend([
            f"- 违例记录总数：{violation_count} 条",
            f"- 涉及船只：{violation_vessels} 艘",
            "",
            _markdown_table(violation_view, ["船 ID", "区域", "类型", "首次进入", "滞留时长(h)", "进入次数"], max_rows=top_n),
        ])

    focus_vessels = []
    if len(top_distance) > 0:
        focus_vessels.append(f"航程最高船 {int(top_distance.iloc[0]['船 ID'])}")
    if len(top_stop) > 0:
        focus_vessels.append(f"停泊率最高船 {int(top_stop.iloc[0]['船 ID'])}")
    if anomalies is not None and len(anomalies) > 0:
        focus_vessels.append(f"航速异常船 {int(anomalies.iloc[0]['vessel_id'])}")
    if violations is not None and len(violations) > 0:
        focus_vessels.append(f"围栏违例船 {int(violations.iloc[0]['vessel_id'])}")

    lines.extend([
        "",
        "## 5. VTS 值班建议",
        f"- 重点关注：{'、'.join(focus_vessels) if focus_vessels else '本月未形成明显重点关注对象'}。",
        "- 对高航程、高停泊率、高速异常船只进行轨迹复核，结合港区规则判断是否存在异常作业或设备数据跳变。",
        "- 对低速点密集区域开展锚地/渔场识别，可作为后续 DBSCAN 停留点检测的输入。",
        "- 对进入禁航区或敏感区域的船只，应结合实时 AIS、雷达、VHF 通信记录进行人工复核。",
        "",
        "> 本报告基于离线 AIS CSV 数据和 Demo 规则生成，不代表正式海事监管结论。",
        "",
    ])

    return "\n".join(lines)


@st.cache_data(show_spinner=False)
def _cached_report_docx_bytes(report_text: str) -> bytes:
    return markdown_to_docx_bytes(report_text)


@st.cache_data(show_spinner=False)
def _cached_report_pdf_bytes(report_text: str) -> bytes:
    return markdown_to_pdf_bytes(report_text)


def main():
    _log(">>> main() called")

    st.markdown(
        """
        <style>
        html, body, .stApp {
            max-height: 100vh;
            overflow-y: auto !important;
        }
        main .block-container {
            max-width: 100%;
            padding-top: 2rem;
            padding-bottom: 2rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    _log(">>> main() step 1: markdown done")
    st.title("⚓ Maritime VTS Knowledge Agent")
    st.caption("简化版 VTS 海事知识库问答与 AIS 轨迹分析智能体 Demo")

    _log(">>> main() step 2: title done")
    _log(">>> main() step 3: sidebar done, loading AIS")
    st.sidebar.header("系统设置")
    top_k = st.sidebar.slider(
        "RAG 检索片段数量 top_k",
        min_value=1, max_value=8, value=4
    )

    if st.sidebar.button("重建知识库索引"):
        load_vector_store.clear()
        st.rerun()

    _log(">>> main() step 4: loading AIS")
    # 加载 AIS 数据（必须在知识库之前，因为 RAGEngine 需要 vessel_ids）
    try:
        ais_loader, ais_query = load_ais()
        _log(f">>> main() step 5: AIS loaded, {len(ais_loader.registry)} ships")
        registry = ais_loader.registry
        st.sidebar.success(f"AIS 数据加载成功，共 {len(registry)} 艘船，"
                           f"{len(ais_query.df):,} 个轨迹点。")
        ais_agent = AISAgent(ais_query, ais_loader)
        st.session_state.ais_data = ais_query.df
    except Exception as e:
        _log(f">>> AIS ERROR: {e}")
        st.error(f"AIS 数据加载失败：{e}")
        with st.expander("完整错误栈（用于调试）", expanded=False):
            st.code(traceback.format_exc(), language="python")
        st.stop()

    _log(">>> main() step 6: loading vector store")
    # 加载知识库
    try:
        vector_store = load_vector_store()
        _log(f">>> main() step 7: vector store loaded, {len(vector_store.chunks)} chunks")
        rag_engine = RAGEngine(vector_store)
        st.sidebar.success(f"知识库加载成功，共 {len(vector_store.chunks)} 个文本片段。")
    except Exception as e:
        _log(f">>> vector_store ERROR: {e}")
        st.error(f"知识库加载失败：{e}")
        with st.expander("完整错误栈（用于调试）", expanded=False):
            st.code(traceback.format_exc(), language="python")
        st.stop()

    _log(">>> main() step 8: about to create tabs")
    # LLM 状态展示（必须在 rag_engine 实例化之后）
    llm_info = rag_engine.get_llm_info()
    with st.sidebar.expander("🤖 LLM 状态", expanded=False):
        if llm_info["available"]:
            st.success("LLM 已配置")
        else:
            st.warning("LLM 未配置（fallback 模式）")
        st.caption(f"**Model**: `{llm_info['model']}`")
        st.caption(f"**Base URL**: `{llm_info['base_url']}`")
        st.caption(f"**API Key**: `{llm_info['api_key_preview']}`")
        st.caption("修改 `.env` 后需重启 demo")

    st.sidebar.markdown("**AIS 知识库**")
    if "last_ais_knowledge_result" not in st.session_state:
        st.session_state["last_ais_knowledge_result"] = None
    if st.session_state["last_ais_knowledge_result"]:
        r = st.session_state["last_ais_knowledge_result"]
        st.sidebar.success(
            f"✅ 已注入 {r['n_vessels']} 条船只摘要"
            + (f" + {r['n_anomaly_files']} 份异常汇总" if r.get("n_anomaly_files") else ""),
            icon="📥",
        )
        st.sidebar.caption(f"知识库目录：`{r['output_dir']}`")
    if st.sidebar.button("📥 注入 AIS 数据到知识库", help="将每艘船的航行摘要写入知识库，并重建向量索引。"):
        with st.spinner("正在导出 AIS 知识文本..."):
            result = export_all_ais_knowledge(ais_query)
        st.session_state["last_ais_knowledge_result"] = result
        load_vector_store.clear()
        st.rerun()

    main_tabs = [
        "海事知识库问答",
        "AIS 轨迹分析",
        "船舶风险研判",
        "📊 渔场热力图",
        "Demo 说明",
    ]
    active_main_tab = st.radio(
        "主功能区",
        main_tabs,
        horizontal=True,
        label_visibility="collapsed",
        key="main_nav",
    )

    # ==========================
    # Tab 1: 知识库问答
    # ==========================
    if active_main_tab == "???????":
        render_rag_page(rag_engine, top_k, registry, render_sources)

    # ==========================
    # Tab 2: AIS 轨迹分析
    # ==========================
    if active_main_tab == "AIS 轨迹分析":
        st.subheader("AIS 轨迹分析")
        if ais_query is None:
            st.error("AIS 数据加载失败，请检查 dataset/ 文件夹。")
        else:
            active_ais_tab = render_ais_analysis_nav()

            # ---- 轨迹地图可视化 ----
            if active_ais_tab == "🗺️ 轨迹地图可视化":
                st.markdown("**在地图上可视化单船 / 多船轨迹（pydeck · Carto 免费底图，无需 API Key）**")

                col_style, _ = st.columns([1, 3])
                with col_style:
                    map_style = st.selectbox(
                        "底图样式",
                        options=["dark", "light", "road", "satellite"],
                        format_func=lambda x: {
                            "dark": "🌙 深色（推荐）",
                            "light": "☀️ 浅色",
                            "road": "🗺️ 道路",
                            "satellite": "🛰️ 卫星",
                        }[x],
                        index=0,
                        key="map_style_select",
                    )
                    line_width_m = st.slider(
                        "轨迹线宽（米）",
                        min_value=50,
                        max_value=2000,
                        value=500,
                        step=50,
                        key="map_line_width",
                        help="pydeck PathLayer 的宽度单位是米，值越大轨迹越粗",
                    )

                mode = st.radio(
                    "选择模式",
                    ["单船", "多船"],
                    horizontal=True,
                    key="map_mode_radio",
                )

                vessel_ids = []
                if mode == "单船":
                    vessel_id_options = {m["vessel_id"]: m for m in registry}
                    _opts = vessel_id_options

                    def _fmt(vid):
                        info = _opts[vid]
                        return f"{vid} | {info['n_points']} 点 | {info['time_start'][:10]} ~ {info['time_end'][:10]}"

                    selected_map_id = st.selectbox(
                        "选择渔船",
                        options=list(vessel_id_options.keys()),
                        format_func=_fmt,
                        key="map_single_select",
                    )
                    vessel_ids = [selected_map_id]
                else:
                    vessel_labels = [
                        f"{m['vessel_id']} ({m['n_points']} 点, "
                        f"{m['time_start'][:10]} ~ {m['time_end'][:10]})"
                        for m in registry
                    ]
                    vessel_id_map = {
                        label: m["vessel_id"] for label, m in zip(vessel_labels, registry)
                    }
                    selected_labels = st.multiselect(
                        "选择船只（最多选 10 艘）",
                        options=vessel_labels,
                        default=vessel_labels[: min(3, len(vessel_labels))],
                        key="map_multi_select",
                    )
                    vessel_ids = [vessel_id_map[l] for l in selected_labels]

                if vessel_ids:
                    all_traj = ais_query.get_multi_trajectories(vessel_ids)

                    if len(all_traj) == 0:
                        st.warning("所选船只无轨迹数据。")
                    else:
                        palette = [
                            [255, 60, 60], [60, 140, 255], [60, 200, 100],
                            [255, 160, 0], [160, 60, 255], [0, 220, 200],
                            [255, 100, 150], [100, 100, 255], [200, 200, 0],
                            [0, 200, 200],
                        ]
                        vessel_colors = {
                            vid: palette[i % len(palette)]
                            for i, vid in enumerate(vessel_ids)
                        }

                        lat_center = float(all_traj["lat"].mean())
                        lon_center = float(all_traj["lon"].mean())

                        path_data = []
                        for vid in vessel_ids:
                            vdf = all_traj[all_traj["vessel_id"] == vid].sort_values("time")
                            if len(vdf) < 2:
                                continue
                            path_data.append({
                                "path": [
                                    [float(r.lon), float(r.lat)]
                                    for _, r in vdf.iterrows()
                                ],
                                "color": vessel_colors[vid],
                                "vessel_id": vid,
                            })

                        scatter_data = []
                        for vid in vessel_ids:
                            vdf = all_traj[all_traj["vessel_id"] == vid].sort_values("time")
                            if len(vdf) == 0:
                                continue
                            first = vdf.iloc[0]
                            last = vdf.iloc[-1]
                            scatter_data.append({
                                "position": [float(first.lon), float(first.lat)],
                                "color": vessel_colors[vid],
                                "label": f"船 {vid} 起点",
                            })
                            scatter_data.append({
                                "position": [float(last.lon), float(last.lat)],
                                "color": vessel_colors[vid],
                                "label": f"船 {vid} 终点",
                            })

                        tooltip = {
                            "html": "<b>{label}</b>",
                            "style": {"color": "white", "font-size": "12px"},
                        }

                        # 主线层：宽度由滑块控制（米），绑定到数据里的 width 字段
                        for item in path_data:
                            item["width"] = line_width_m

                        deck = _safe_deck(
                            layers=[
                                # 描边层（更宽、半透明黑），让轨迹从底图背景上跳出来
                                pdk.Layer(
                                    "PathLayer",
                                    data=path_data,
                                    get_width="width * 2.5",
                                    get_color=[0, 0, 0, 100],
                                    pickable=False,
                                ),
                                # 主线层
                                pdk.Layer(
                                    "PathLayer",
                                    data=path_data,
                                    get_width="width",
                                    get_color="color",
                                    pickable=True,
                                ),
                                # 起终点圆点
                                pdk.Layer(
                                    "ScatterplotLayer",
                                    data=scatter_data,
                                    get_position="position",
                                    get_fill_color="color",
                                    get_radius=2000,
                                    pickable=True,
                                ),
                            ],
                            map_style=map_style,
                            initial_view_state=pdk.ViewState(
                                latitude=lat_center,
                                longitude=lon_center,
                                zoom=10,
                                pitch=40,
                            ),
                            height=520,
                            tooltip=tooltip,
                        )
                        st.pydeck_chart(deck, use_container_width=True)

                        legend_cols = st.columns(min(len(vessel_ids), 5))
                        for i, vid in enumerate(vessel_ids):
                            with legend_cols[i % len(legend_cols)]:
                                r, g, b = vessel_colors[vid]
                                st.markdown(
                                    f"<span style='color:rgb({r},{g},{b});font-size:20px;'>●</span> "
                                    f"船 {vid}",
                                    unsafe_allow_html=True,
                                )

                        st.markdown("**选中船只轨迹统计**")
                        stat_cols = st.columns(min(len(vessel_ids), 5))
                        for i, vid in enumerate(vessel_ids):
                            with stat_cols[i % len(stat_cols)]:
                                summary = ais_query.vessel_summary(vid)
                                if summary:
                                    st.metric(
                                        f"船 {vid}",
                                        f"{summary['n_points']} 点",
                                        f"{summary['total_distance_nm']} 海里",
                                    )

            # ---- 单船 ----
            if active_ais_tab == "单船轨迹回放":
                col_select, col_view = st.columns([1, 2])

                with col_select:
                    st.markdown("**船只选择**")
                    vessel_options = {
                        f"{m['vessel_id']} | {m['n_points']}点 | "
                        f"{m['time_start'][:10]}~{m['time_end'][:10]} | "
                        f"停泊率{m['stopped_ratio']}%": m["vessel_id"]
                        for m in registry
                    }
                    selected_label = st.selectbox("选择渔船", options=list(vessel_options.keys()))
                    selected_id = vessel_options[selected_label]

                    st.markdown("**快速筛选**")
                    stop_filter = st.selectbox(
                        "停泊率筛选",
                        ["全部", "持续航行 (<5%)", "正常作业 (5~30%)",
                         "定点作业 (30~50%)", "锚泊待命 (>50%)"]
                    )

                    if stop_filter != "全部":
                        def match_ratio(m, f):
                            r = m["stopped_ratio"]
                            if f == "持续航行 (<5%)": return r < 5
                            if f == "正常作业 (5~30%)": return 5 <= r < 30
                            if f == "定点作业 (30~50%)": return 30 <= r < 50
                            if f == "锚泊待命 (>50%)": return r >= 50
                            return True
                        filtered = [m for m in registry if match_ratio(m, stop_filter)]
                        filtered_opts = {
                            f"{m['vessel_id']} | {m['n_points']}点 | "
                            f"{m['time_start'][:10]} | 停泊率{m['stopped_ratio']}%": m["vessel_id"]
                            for m in filtered
                        }
                        if filtered_opts:
                            selected_label = st.selectbox(
                                "筛选结果", options=list(filtered_opts.keys())
                            )
                            selected_id = filtered_opts[selected_label]

                    # 年月筛选
                    months = sorted(set(
                        m["time_start"][:7] for m in registry
                    ))
                    selected_month = st.selectbox(
                        "月份筛选（可选）",
                        ["全部月份"] + months
                    )

                    if selected_month != "全部月份":
                        month_vessels = ais_query.get_vessels_by_month(
                            int(selected_month[:4]),
                            int(selected_month[5:7])
                        )
                        mv_opts = {
                            f"{m['vessel_id']} | {m['n_points']}点 | "
                            f"{m['time_start'][:10]} | 停泊率{m['stopped_ratio']}%": m["vessel_id"]
                            for m in month_vessels
                        }
                        if mv_opts:
                            selected_label = st.selectbox(
                                f"{selected_month} 活跃船只", options=list(mv_opts.keys())
                            )
                            selected_id = mv_opts[selected_label]
                        else:
                            st.info(f"{selected_month} 无活跃船只。")
                            selected_id = None

                if selected_id is not None:
                    summary = ais_query.vessel_summary(selected_id)

                    with col_view:
                        st.markdown(f"### 渔船 {selected_id} 统计摘要")
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            st.metric("数据点数", f"{summary['n_points']}")
                            st.metric("航行时长", f"{summary['duration_hours']}h")
                        with col2:
                            st.metric("平均航速", f"{summary['sog_mean']} kn")
                            st.metric("最高航速", f"{summary['sog_max']} kn")
                        with col3:
                            st.metric("活动中心",
                                      f"{summary['lat_center']}N, {summary['lon_center']}E")
                            st.metric("估算航程",
                                      f"{summary['total_distance_nm']} 海里")
                        with col4:
                            st.metric("停泊率", f"{summary['stopped_ratio_pct']}%")
                            st.metric("中位航速", f"{summary['sog_median']} kn")

                        sb = summary.get("speed_buckets", {})
                        st.markdown("**速度分布**")
                        c1, c2, c3, c4 = st.columns(4)
                        with c1:
                            st.metric("停泊 (0~0.5kn)", int(sb.get("停泊 (0-0.5kn)", 0)))
                        with c2:
                            st.metric("低速 (0.5~3kn)", int(sb.get("低速 (0.5-3kn)", 0)))
                        with c3:
                            st.metric("中速 (3~6kn)", int(sb.get("中速 (3-6kn)", 0)))
                        with c4:
                            st.metric("高速 (>6kn)", int(sb.get("高速 (>6kn)", 0)))

                        st.markdown(f"**轨迹坐标**（{len(summary['lat_range'])} 条范围）")
                        st.write(
                            f"纬度范围：{summary['lat_range'][0]}°N ~ "
                            f"{summary['lat_range'][1]}°N"
                        )
                        st.write(
                            f"经度范围：{summary['lon_range'][0]}°E ~ "
                            f"{summary['lon_range'][1]}°E"
                        )
                        st.write(f"时间范围：{summary['time_start'][:19]} ~ "
                                 f"{summary['time_end'][:19]}")

                        # 获取轨迹数据用于时间轴回放和轨迹预览
                        traj = ais_query.get_trajectory(selected_id)
                        if len(traj) > 0:
                            traj = traj.sort_values("time").reset_index(drop=True)
                            st.markdown("**时间轴轨迹回放**")
                            if len(traj) == 1:
                                replay_idx = 0
                                st.info("该船只有 1 个轨迹点，无法形成轨迹线。")
                            else:
                                default_idx = min(max(1, len(traj) // 4), len(traj) - 1)
                                replay_idx = st.slider(
                                    "拖动时间轴查看历史轨迹",
                                    min_value=0,
                                    max_value=len(traj) - 1,
                                    value=default_idx,
                                    step=1,
                                    key=f"replay_idx_{selected_id}",
                                    format="%d",
                                    help="滑块位置对应轨迹点序号，地图显示从起点到该时间点的已走轨迹。",
                                )

                            replay_df = traj.iloc[: replay_idx + 1].copy()
                            current = replay_df.iloc[-1]
                            first = traj.iloc[0]
                            last = traj.iloc[-1]

                            replay_cols = st.columns(4)
                            with replay_cols[0]:
                                st.metric("当前时间", pd.Timestamp(current["time"]).strftime("%m-%d %H:%M"))
                            with replay_cols[1]:
                                st.metric("当前航速", f"{float(current['sog']):.1f} kn")
                            with replay_cols[2]:
                                st.metric("当前航向", f"{float(current['cog']):.0f}°")
                            with replay_cols[3]:
                                st.metric("已回放点数", f"{len(replay_df)} / {len(traj)}")

                            replay_path = [[float(r.lon), float(r.lat)] for _, r in replay_df.iterrows()]
                            replay_layers = []
                            if len(replay_path) >= 2:
                                replay_layers.append(
                                    pdk.Layer(
                                        "PathLayer",
                                        data=[{
                                            "path": replay_path,
                                            "color": [60, 140, 255, 230],
                                            "width": 500,
                                            "label": f"船 {selected_id} 已走轨迹",
                                        }],
                                        get_path="path",
                                        get_width="width",
                                        get_color="color",
                                        pickable=True,
                                    )
                                )

                            replay_points = [
                                {
                                    "position": [float(first.lon), float(first.lat)],
                                    "color": [60, 200, 100, 220],
                                    "radius": 1800,
                                    "label": f"船 {selected_id} 起点",
                                },
                                {
                                    "position": [float(current.lon), float(current.lat)],
                                    "color": [255, 90, 50, 240],
                                    "radius": 2600,
                                    "label": (
                                        f"船 {selected_id} 当前点 | "
                                        f"{pd.Timestamp(current['time']).strftime('%Y-%m-%d %H:%M')} | "
                                        f"{float(current['sog']):.1f} kn"
                                    ),
                                },
                                {
                                    "position": [float(last.lon), float(last.lat)],
                                    "color": [180, 180, 180, 180],
                                    "radius": 1600,
                                    "label": f"船 {selected_id} 终点",
                                },
                            ]
                            replay_layers.append(
                                pdk.Layer(
                                    "ScatterplotLayer",
                                    data=replay_points,
                                    get_position="position",
                                    get_fill_color="color",
                                    get_radius="radius",
                                    pickable=True,
                                )
                            )

                            replay_deck = _safe_deck(
                                layers=replay_layers,
                                map_style="dark",
                                initial_view_state=pdk.ViewState(
                                    latitude=float(replay_df["lat"].mean()),
                                    longitude=float(replay_df["lon"].mean()),
                                    zoom=10,
                                    pitch=35,
                                ),
                                height=460,
                                tooltip={
                                    "html": "<b>{label}</b>",
                                    "style": {"color": "white", "font-size": "12px"},
                                },
                            )
                            st.pydeck_chart(replay_deck, use_container_width=True)

                            st.markdown("**轨迹预览（前10条）**")
                            display_df = traj[["time", "lat", "lon", "sog", "cog"]].head(10).copy()
                            display_df["time"] = display_df["time"].dt.strftime("%Y-%m-%d %H:%M")
                            st.dataframe(
                                display_df.rename(columns={
                                    "time": "时间", "lat": "纬度", "lon": "经度",
                                    "sog": "航速(kn)", "cog": "航向(°)"
                                }),
                                use_container_width=True,
                                hide_index=True,
                            )

            # ---- 航次识别 ----
            if active_ais_tab == "🧭 航次识别":
                st.markdown("**基于停泊边界的轨迹分段 / 航次识别**")

                col_voyage_1, col_voyage_2, col_voyage_3, col_voyage_4 = st.columns([2, 1, 1, 1])
                vessel_label_map = {
                    f"{m['vessel_id']} | {m['n_points']}点 | {m['time_start'][:10]}~{m['time_end'][:10]}": m["vessel_id"]
                    for m in registry
                }
                with col_voyage_1:
                    selected_voyage_labels = st.multiselect(
                        "选择船只（可多选）",
                        options=list(vessel_label_map.keys()),
                        default=list(vessel_label_map.keys())[:1],
                        key="voyage_vessel_select",
                    )
                with col_voyage_2:
                    voyage_stop_threshold = st.slider(
                        "低速阈值(kn)",
                        min_value=0.1,
                        max_value=2.0,
                        value=0.5,
                        step=0.1,
                        key="voyage_stop_threshold",
                    )
                with col_voyage_3:
                    voyage_min_stop_hours = st.slider(
                        "停泊边界(h)",
                        min_value=0.5,
                        max_value=24.0,
                        value=3.0,
                        step=0.5,
                        key="voyage_min_stop_hours",
                    )
                with col_voyage_4:
                    voyage_min_trip_hours = st.slider(
                        "最短航次(h)",
                        min_value=0.5,
                        max_value=12.0,
                        value=1.0,
                        step=0.5,
                        key="voyage_min_trip_hours",
                    )

                selected_voyage_ids = [vessel_label_map[l] for l in selected_voyage_labels]
                if st.button("🧭 执行航次识别", type="primary", key="run_voyage_segmentation"):
                    if not selected_voyage_ids:
                        st.warning("请至少选择一艘船。")
                        st.session_state.voyage_segments = None
                    else:
                        with st.spinner("正在识别航次..."):
                            st.session_state.voyage_segments = segment_voyages_for_ids(
                                ais_query,
                                selected_voyage_ids,
                                stop_threshold=voyage_stop_threshold,
                                min_stop_hours=voyage_min_stop_hours,
                                min_trip_hours=voyage_min_trip_hours,
                            )

                voyages = st.session_state.get("voyage_segments")
                if voyages is None:
                    st.info("设置参数后点击“执行航次识别”。连续低速停泊超过边界时长会被视为航次切分点。")
                else:
                    st.markdown(summarize_voyages(voyages))
                    if len(voyages) == 0:
                        st.warning("当前参数下没有识别出有效航次。可以降低停泊边界或最短航次时长。")
                    else:
                        stat_cols = st.columns(4)
                        with stat_cols[0]:
                            st.metric("航次数", len(voyages))
                        with stat_cols[1]:
                            st.metric("涉及船只", voyages["vessel_id"].nunique())
                        with stat_cols[2]:
                            st.metric("累计航程", f"{voyages['distance_nm'].sum():.1f} nm")
                        with stat_cols[3]:
                            st.metric("最长航次", f"{voyages['distance_nm'].max():.1f} nm")

                        display_voyages = voyages.rename(columns={
                            "vessel_id": "船 ID",
                            "trip_id": "航次",
                            "start_time": "开始时间",
                            "end_time": "结束时间",
                            "duration_h": "时长(h)",
                            "n_points": "轨迹点数",
                            "distance_nm": "估算航程(nm)",
                            "avg_sog": "平均航速(kn)",
                            "max_sog": "最高航速(kn)",
                            "start_lat": "起点纬度",
                            "start_lon": "起点经度",
                            "end_lat": "终点纬度",
                            "end_lon": "终点经度",
                        })
                        st.dataframe(display_voyages, use_container_width=True, hide_index=True)

                        st.download_button(
                            "下载航次识别 CSV",
                            data=display_voyages.to_csv(index=False).encode("utf-8-sig"),
                            file_name="voyage_segments.csv",
                            mime="text/csv",
                            key="download_voyage_segments_csv",
                            on_click="ignore",
                        )

                        map_options = [
                            f"船 {int(r['vessel_id'])} - 航次 {int(r['trip_id'])} | {float(r['distance_nm']):.1f} nm"
                            for _, r in voyages.iterrows()
                        ]
                        selected_trip_label = st.selectbox(
                            "在地图上查看某个航次",
                            options=map_options,
                            key="voyage_trip_map_select",
                        )
                        selected_trip = voyages.iloc[map_options.index(selected_trip_label)]
                        trip_df = ais_query.get_trajectory(
                            int(selected_trip["vessel_id"]),
                            pd.Timestamp(selected_trip["start_time"]),
                            pd.Timestamp(selected_trip["end_time"]),
                        )
                        if len(trip_df) >= 2:
                            trip_path = [{
                                "path": [[float(r.lon), float(r.lat)] for _, r in trip_df.iterrows()],
                                "color": [52, 211, 153],
                                "width": 700,
                            }]
                            trip_points = [
                                {
                                    "position": [float(trip_df.iloc[0].lon), float(trip_df.iloc[0].lat)],
                                    "color": [59, 130, 246],
                                    "radius": 1800,
                                    "label": "起点",
                                },
                                {
                                    "position": [float(trip_df.iloc[-1].lon), float(trip_df.iloc[-1].lat)],
                                    "color": [239, 68, 68],
                                    "radius": 1800,
                                    "label": "终点",
                                },
                            ]
                            voyage_deck = _safe_deck(
                                layers=[
                                    pdk.Layer(
                                        "PathLayer",
                                        data=trip_path,
                                        get_path="path",
                                        get_color="color",
                                        get_width="width",
                                        pickable=True,
                                    ),
                                    pdk.Layer(
                                        "ScatterplotLayer",
                                        data=trip_points,
                                        get_position="position",
                                        get_fill_color="color",
                                        get_radius="radius",
                                        pickable=True,
                                    ),
                                ],
                                map_style="dark",
                                initial_view_state=pdk.ViewState(
                                    latitude=float(trip_df["lat"].mean()),
                                    longitude=float(trip_df["lon"].mean()),
                                    zoom=9,
                                    pitch=35,
                                ),
                                height=480,
                                tooltip={"html": "<b>{label}</b>"},
                            )
                            st.pydeck_chart(voyage_deck, use_container_width=True)

            # ---- 多船 ----
            if active_ais_tab == "多船联合分析":
                st.markdown("**选择多艘船进行联合分析**")
                vessel_labels = [
                    f"{m['vessel_id']} ({m['n_points']}点, "
                    f"{m['time_start'][:10]}~{m['time_end'][:10]})"
                    for m in registry
                ]
                vessel_id_map = {label: m["vessel_id"] for label, m in zip(vessel_labels, registry)}

                selected_labels = st.multiselect(
                    "选择船只（最多选10艘）",
                    options=vessel_labels,
                    default=vessel_labels[:3] if len(vessel_labels) >= 3 else vessel_labels[:1],
                )
                selected_ids = [vessel_id_map[l] for l in selected_labels]

                if selected_ids:
                    col_left, col_right = st.columns([1, 1])

                    with col_left:
                        st.markdown("**对比统计**")
                        comp = ais_query.multi_vessel_comparison(selected_ids)
                        rows = []
                        for vid, s in comp.items():
                            rows.append({
                                "渔船ID": vid,
                                "数据点": s["n_points"],
                                "时长(h)": s["duration_hours"],
                                "均速(kn)": s["sog_mean"],
                                "最高速(kn)": s["sog_max"],
                                "停泊率%": s["stopped_ratio_pct"],
                                "中心纬度": s["lat_center"],
                                "中心经度": s["lon_center"],
                                "估算航程(nm)": s["total_distance_nm"],
                            })
                        comp_df = pd.DataFrame(rows)
                        st.dataframe(comp_df, use_container_width=True, hide_index=True)

                    with col_right:
                        st.markdown("**轨迹热力预览**")
                        for vid in selected_ids:
                            summary = ais_query.vessel_summary(vid)
                            st.write(
                                f"船 {vid}: "
                                f"LAT {summary['lat_range'][0]:.4f}~{summary['lat_range'][1]:.4f}N, "
                                f"LON {summary['lon_range'][0]:.4f}~{summary['lon_range'][1]:.4f}E, "
                                f"{summary['n_points']} 点"
                            )

                        # 找重叠船只对
                        st.markdown("**时间重叠分析**")
                        overlap_pairs = []
                        for i in range(len(selected_ids)):
                            for j in range(i + 1, len(selected_ids)):
                                s1 = comp[selected_ids[i]]
                                s2 = comp[selected_ids[j]]
                                ts1, te1 = pd.Timestamp(s1["time_start"]), pd.Timestamp(s1["time_end"])
                                ts2, te2 = pd.Timestamp(s2["time_start"]), pd.Timestamp(s2["time_end"])
                                if ts1 <= te2 and ts2 <= te1:
                                    ov = min(te1, te2) - max(ts1, ts2)
                                    overlap_pairs.append(
                                        f"船 {selected_ids[i]} & 船 {selected_ids[j]}: "
                                        f"重叠 {str(ov.astype('timedelta64[h]')).replace('T', ' ').replace('+', '')}h"
                                    )
                        if overlap_pairs:
                            for p in overlap_pairs:
                                st.write(f"- {p}")
                        else:
                            st.info("所选船只时间不重叠。")

            # ---- 停泊点分布 ----
            if active_ais_tab == "⚓ 停泊点分布":
                st.markdown("**停泊点分布可视化**")

                col_stop_1, col_stop_2, col_stop_3 = st.columns([1, 1, 2])
                with col_stop_1:
                    stop_threshold = st.slider(
                        "停泊速度阈值（节）",
                        min_value=0.1,
                        max_value=2.0,
                        value=0.5,
                        step=0.1,
                        key="stop_points_threshold",
                    )
                with col_stop_2:
                    stop_radius = st.slider(
                        "点半径（米）",
                        min_value=100,
                        max_value=3000,
                        value=900,
                        step=100,
                        key="stop_points_radius",
                    )

                stop_vessel_labels = [
                    f"{m['vessel_id']} ({m['n_points']} 点, 停泊率 {m['stopped_ratio']}%)"
                    for m in registry
                ]
                stop_vessel_map = {
                    label: m["vessel_id"] for label, m in zip(stop_vessel_labels, registry)
                }
                with col_stop_3:
                    selected_stop_labels = st.multiselect(
                        "选择船只（留空 = 全部）",
                        options=stop_vessel_labels,
                        default=[],
                        key="stop_points_vessels",
                    )

                stop_df = ais_query.df[ais_query.df["sog"] < stop_threshold].copy()
                if selected_stop_labels:
                    selected_stop_ids = [stop_vessel_map[l] for l in selected_stop_labels]
                    stop_df = stop_df[stop_df["vessel_id"].isin(selected_stop_ids)]
                else:
                    selected_stop_ids = [m["vessel_id"] for m in registry]

                if len(stop_df) == 0:
                    st.warning("当前筛选条件下没有停泊点。")
                else:
                    total_scope_points = len(
                        ais_query.df[ais_query.df["vessel_id"].isin(selected_stop_ids)]
                    )
                    stop_ratio = len(stop_df) / total_scope_points * 100 if total_scope_points else 0
                    top_stop_vessels = (
                        stop_df.groupby("vessel_id")
                        .size()
                        .sort_values(ascending=False)
                        .head(5)
                    )

                    stat_stop_cols = st.columns(4)
                    with stat_stop_cols[0]:
                        st.metric("停泊点数", f"{len(stop_df):,}")
                    with stat_stop_cols[1]:
                        st.metric("涉及船只", stop_df["vessel_id"].nunique())
                    with stat_stop_cols[2]:
                        st.metric("停泊点占比", f"{stop_ratio:.1f}%")
                    with stat_stop_cols[3]:
                        top_stop_vid = int(top_stop_vessels.index[0]) if len(top_stop_vessels) else "-"
                        st.metric("停泊点最多", f"船 {top_stop_vid}" if top_stop_vid != "-" else "-")

                    stop_plot_df = stop_df[["vessel_id", "time", "lat", "lon", "sog"]].copy()
                    stop_plot_df["position"] = stop_plot_df.apply(
                        lambda r: [float(r["lon"]), float(r["lat"])],
                        axis=1,
                    )
                    stop_plot_df["label"] = stop_plot_df.apply(
                        lambda r: (
                            f"船 {int(r['vessel_id'])} | "
                            f"{pd.Timestamp(r['time']).strftime('%Y-%m-%d %H:%M')} | "
                            f"{float(r['sog']):.1f} kn"
                        ),
                        axis=1,
                    )
                    stop_plot_df["radius"] = stop_radius

                    stop_deck = _safe_deck(
                        layers=[
                            pdk.Layer(
                                "ScatterplotLayer",
                                data=stop_plot_df,
                                get_position="position",
                                get_fill_color=[255, 180, 0, 120],
                                get_line_color=[255, 255, 255, 80],
                                get_line_width=80,
                                get_radius="radius",
                                pickable=True,
                            )
                        ],
                        map_style="dark",
                        initial_view_state=pdk.ViewState(
                            latitude=float(stop_plot_df["lat"].mean()),
                            longitude=float(stop_plot_df["lon"].mean()),
                            zoom=8,
                            pitch=25,
                        ),
                        height=520,
                        tooltip={
                            "html": "<b>{label}</b>",
                            "style": {"color": "white", "font-size": "12px"},
                        },
                    )
                    st.pydeck_chart(stop_deck, use_container_width=True)

                    st.markdown("**停泊点最多的船只 Top 5**")
                    top_stop_df = top_stop_vessels.reset_index()
                    top_stop_df.columns = ["船 ID", "停泊点数"]
                    st.dataframe(top_stop_df, use_container_width=True, hide_index=True)

            # ---- 锚地 / 停留点聚类 ----
            if active_ais_tab == "⚓ 锚地聚类":
                st.markdown("**DBSCAN 锚地 / 停留点检测**")

                col_anchor_1, col_anchor_2, col_anchor_3 = st.columns([1, 1, 1])
                with col_anchor_1:
                    anchor_stop_threshold = st.slider(
                        "低速阈值（节）",
                        min_value=0.1,
                        max_value=2.0,
                        value=0.5,
                        step=0.1,
                        key="anchor_stop_threshold",
                        help="低于该速度的 AIS 点会进入 DBSCAN 聚类。",
                    )
                with col_anchor_2:
                    anchor_eps_nm = st.slider(
                        "聚类半径 eps（海里）",
                        min_value=0.2,
                        max_value=5.0,
                        value=1.0,
                        step=0.1,
                        key="anchor_eps_nm",
                        help="DBSCAN 邻域半径。1 海里约等于 0.0167 纬度。",
                    )
                with col_anchor_3:
                    anchor_min_samples = st.slider(
                        "最少点数 min_samples",
                        min_value=5,
                        max_value=100,
                        value=25,
                        step=5,
                        key="anchor_min_samples",
                    )

                anchor_vessel_labels = [
                    f"{m['vessel_id']} ({m['n_points']} 点, 停泊率 {m['stopped_ratio']}%)"
                    for m in registry
                ]
                anchor_vessel_map = {
                    label: m["vessel_id"] for label, m in zip(anchor_vessel_labels, registry)
                }
                selected_anchor_labels = st.multiselect(
                    "选择船只（留空 = 全部）",
                    options=anchor_vessel_labels,
                    default=[],
                    key="anchor_vessels",
                )
                if selected_anchor_labels:
                    anchor_vessel_ids = [anchor_vessel_map[l] for l in selected_anchor_labels]
                    anchor_df = ais_query.df[ais_query.df["vessel_id"].isin(anchor_vessel_ids)].copy()
                else:
                    anchor_df = ais_query.df.copy()

                if st.button("🔍 执行锚地聚类", type="primary", key="run_anchor_cluster"):
                    with st.spinner("正在进行 DBSCAN 聚类..."):
                        clusters, clustered_points = detect_anchor_clusters(
                            anchor_df,
                            stop_threshold=anchor_stop_threshold,
                            eps_nm=anchor_eps_nm,
                            min_samples=anchor_min_samples,
                        )
                        st.session_state.anchor_clusters = clusters
                        st.session_state.anchor_cluster_points = clustered_points
                        st.session_state.anchor_cluster_params = {
                            "stop_threshold": anchor_stop_threshold,
                            "eps_nm": anchor_eps_nm,
                            "min_samples": anchor_min_samples,
                            "n_scope_points": len(anchor_df),
                        }

                clusters = st.session_state.get("anchor_clusters")
                clustered_points = st.session_state.get("anchor_cluster_points")
                cluster_params = st.session_state.get("anchor_cluster_params", {})

                if clusters is None or clustered_points is None:
                    st.info("设置参数后点击“执行锚地聚类”，系统会基于低速 AIS 点识别疑似锚地/停留区。")
                else:
                    st.markdown(summarize_anchor_clusters(clusters, clustered_points))
                    n_noise = int((clustered_points["cluster_id"] == -1).sum()) if len(clustered_points) else 0
                    stat_anchor_cols = st.columns(4)
                    with stat_anchor_cols[0]:
                        st.metric("停留簇数量", len(clusters))
                    with stat_anchor_cols[1]:
                        st.metric("低速点数", f"{len(clustered_points):,}")
                    with stat_anchor_cols[2]:
                        st.metric("噪声点", f"{n_noise:,}")
                    with stat_anchor_cols[3]:
                        st.metric("分析轨迹点", f"{cluster_params.get('n_scope_points', len(anchor_df)):,}")

                    if len(clusters) > 0:
                        map_clusters = clusters.copy()
                        max_points = max(float(map_clusters["n_points"].max()), 1.0)
                        map_clusters["position"] = map_clusters.apply(
                            lambda r: [float(r["center_lon"]), float(r["center_lat"])],
                            axis=1,
                        )
                        map_clusters["radius"] = map_clusters["n_points"].apply(
                            lambda n: 1200 + min(7000, float(n) / max_points * 7000)
                        )
                        map_clusters["color"] = map_clusters["n_vessels"].apply(
                            lambda n: [255, 80, 60, 220] if n >= 5 else [255, 190, 40, 210]
                        )
                        map_clusters["label"] = map_clusters.apply(
                            lambda r: (
                                f"簇 {int(r['cluster_id'])} | "
                                f"{int(r['n_points'])} 点 | "
                                f"{int(r['n_vessels'])} 艘船 | "
                                f"半径 {float(r['radius_nm']):.1f} nm"
                            ),
                            axis=1,
                        )

                        clustered_non_noise = clustered_points[clustered_points["cluster_id"] >= 0].copy()
                        point_layer_data = []
                        if len(clustered_non_noise) > 0:
                            sample_points = clustered_non_noise
                            if len(sample_points) > 8000:
                                sample_points = sample_points.sample(8000, random_state=7)
                            point_layer_data = [{
                                "position": [float(r.lon), float(r.lat)],
                                "color": [255, 210, 90, 70],
                                "radius": 450,
                                "label": f"船 {int(r.vessel_id)} | 簇 {int(r.cluster_id)}",
                            } for _, r in sample_points.iterrows()]

                        anchor_layers = []
                        if point_layer_data:
                            anchor_layers.append(
                                pdk.Layer(
                                    "ScatterplotLayer",
                                    data=point_layer_data,
                                    get_position="position",
                                    get_fill_color="color",
                                    get_radius="radius",
                                    pickable=True,
                                )
                            )
                        anchor_layers.append(
                            pdk.Layer(
                                "ScatterplotLayer",
                                data=map_clusters,
                                get_position="position",
                                get_fill_color="color",
                                get_line_color=[255, 255, 255, 180],
                                get_line_width=120,
                                get_radius="radius",
                                pickable=True,
                            )
                        )

                        anchor_deck = _safe_deck(
                            layers=anchor_layers,
                            map_style="dark",
                            initial_view_state=pdk.ViewState(
                                latitude=float(map_clusters["center_lat"].mean()),
                                longitude=float(map_clusters["center_lon"].mean()),
                                zoom=8,
                                pitch=25,
                            ),
                            height=520,
                            tooltip={
                                "html": "<b>{label}</b>",
                                "style": {"color": "white", "font-size": "12px"},
                            },
                        )
                        st.pydeck_chart(anchor_deck, use_container_width=True)

                        display_clusters = clusters.rename(columns={
                            "cluster_id": "簇 ID",
                            "center_lat": "中心纬度",
                            "center_lon": "中心经度",
                            "n_points": "低速点数",
                            "n_vessels": "涉及船只",
                            "first_time": "最早时间",
                            "last_time": "最晚时间",
                            "duration_h": "时间跨度(h)",
                            "avg_sog": "平均航速(kn)",
                            "radius_nm": "簇半径(nm)",
                        })
                        st.dataframe(display_clusters, use_container_width=True, hide_index=True)

                        csv = display_clusters.to_csv(index=False).encode("utf-8-sig")
                        st.download_button(
                            "下载锚地聚类 CSV",
                            data=csv,
                            file_name="anchor_clusters.csv",
                            mime="text/csv",
                            key="download_anchor_clusters_csv",
                            on_click="ignore",
                        )
                    else:
                        st.warning("当前参数下没有形成有效停留簇。可以适当增大 eps 或降低 min_samples。")

            # ---- 航行排行榜 ----
            if active_ais_tab == "🏆 航行排行榜":
                st.markdown("**100 艘船航行指标排行榜**")

                rank_rows = []
                for meta in registry:
                    vid = meta["vessel_id"]
                    s = ais_query.vessel_summary(vid)
                    if not s:
                        continue
                    rank_rows.append({
                        "船 ID": vid,
                        "估算航程(nm)": s["total_distance_nm"],
                        "航行时长(h)": s["duration_hours"],
                        "平均航速(kn)": s["sog_mean"],
                        "最高航速(kn)": s["sog_max"],
                        "停泊率(%)": s["stopped_ratio_pct"],
                        "数据点数": s["n_points"],
                        "开始时间": s["time_start"][:19],
                        "结束时间": s["time_end"][:19],
                    })

                rank_df = pd.DataFrame(rank_rows)
                if len(rank_df) == 0:
                    st.warning("暂无可排行的船只数据。")
                else:
                    col_rank_1, col_rank_2, col_rank_3 = st.columns([1, 1, 2])
                    with col_rank_1:
                        sort_by = st.selectbox(
                            "排序指标",
                            ["估算航程(nm)", "航行时长(h)", "最高航速(kn)", "停泊率(%)", "数据点数", "平均航速(kn)"],
                            key="ranking_sort_by",
                        )
                    with col_rank_2:
                        top_n = st.slider(
                            "显示 Top N",
                            min_value=5,
                            max_value=min(100, len(rank_df)),
                            value=min(20, len(rank_df)),
                            step=5,
                            key="ranking_top_n",
                        )

                    sorted_rank_df = (
                        rank_df.sort_values(sort_by, ascending=False)
                        .head(top_n)
                        .reset_index(drop=True)
                    )
                    sorted_rank_df.insert(0, "排名", range(1, len(sorted_rank_df) + 1))

                    rank_stat_cols = st.columns(4)
                    with rank_stat_cols[0]:
                        leader = sorted_rank_df.iloc[0]
                        st.metric("榜首船只", f"船 {int(leader['船 ID'])}")
                    with rank_stat_cols[1]:
                        st.metric(sort_by, f"{leader[sort_by]:,.1f}" if isinstance(leader[sort_by], float) else leader[sort_by])
                    with rank_stat_cols[2]:
                        st.metric("总船只数", len(rank_df))
                    with rank_stat_cols[3]:
                        st.metric("平均航程", f"{rank_df['估算航程(nm)'].mean():.1f} nm")

                    st.dataframe(sorted_rank_df, use_container_width=True, hide_index=True)

                    chart_df = sorted_rank_df[["船 ID", sort_by]].copy()
                    chart_df["船 ID"] = chart_df["船 ID"].astype(str)
                    st.bar_chart(chart_df.set_index("船 ID")[sort_by])

                    csv = sorted_rank_df.to_csv(index=False).encode("utf-8-sig")
                    st.download_button(
                        "下载当前排行榜 CSV",
                        data=csv,
                        file_name=f"vessel_ranking_{sort_by}.csv",
                        mime="text/csv",
                        key="download_ranking_csv",
                        on_click="ignore",
                    )

            # ---- 月度报告 ----
            if active_ais_tab == "?? ????":
                render_monthly_report_page(
                    ais_query=ais_query,
                    restricted_zones=RESTRICTED_ZONES,
                    calc_monthly_vessel_rows=_calc_monthly_vessel_rows,
                    build_monthly_report_text=build_monthly_report_text,
                    cached_report_docx_bytes=_cached_report_docx_bytes,
                    cached_report_pdf_bytes=_cached_report_pdf_bytes,
                )

            # ---- 航速异常检测 ----
            if active_ais_tab == "🤒 航速异常检测":
                st.markdown(
                    "**基于 Z-Score 的航速异常检测**\n\n"
                    "对每条船的航速分布单独计算 μ、σ，"
                    "将 `|Z| > 阈值` 的点标记为异常（过高/过低）。"
                    "连续停泊段会被切除，避免 σ 被 0 值拉低导致误报。"
                )

                col_a1, col_a2, col_a3 = st.columns([1, 1, 1])
                with col_a1:
                    z_threshold = st.slider(
                        "Z-Score 阈值",
                        min_value=1.5,
                        max_value=4.0,
                        value=2.5,
                        step=0.1,
                        key="z_threshold",
                        help="|Z| > 阈值判定为异常。2.0≈95%置信，2.5≈99%置信，3.0≈99.7%置信",
                    )
                with col_a2:
                    min_n_points = st.slider(
                        "最少记录数",
                        min_value=3,
                        max_value=20,
                        value=5,
                        step=1,
                        key="anomaly_min_n",
                        help="少于该数的船跳过（避免 σ≈0 导致的虚假异常）",
                    )
                with col_a3:
                    detect_mode = st.radio(
                        "检测模式",
                        ["按船分析（推荐）", "全局分析"],
                        horizontal=True,
                        key="detect_mode",
                    )

                st.markdown("**选择要检测的船只（可多选，留空默认检测全部）**")
                all_vessel_options = {
                    f"{m['vessel_id']} | {m['n_points']}点 | "
                    f"{m['time_start'][:10]}~{m['time_end'][:10]}": m["vessel_id"]
                    for m in registry
                }
                selected_anomaly_labels = st.multiselect(
                    "船只",
                    options=list(all_vessel_options.keys()),
                    default=[],
                    key="anomaly_vessel_select",
                )
                anomaly_vessel_ids = (
                    [all_vessel_options[l] for l in selected_anomaly_labels]
                    if selected_anomaly_labels
                    else [m["vessel_id"] for m in registry]
                )

                if st.button("🔍 执行航速异常检测", type="primary", key="run_anomaly_btn"):
                    if not anomaly_vessel_ids:
                        st.warning("无可检测船只。")
                    else:
                        with st.spinner("正在计算..."):
                            try:
                                all_traj = ais_query.get_multi_trajectories(anomaly_vessel_ids)
                                if len(all_traj) == 0:
                                    st.warning("所选船只无轨迹数据。")
                                else:
                                    if detect_mode == "按船分析（推荐）":
                                        anomalies = detect_by_vessel(
                                            all_traj,
                                            threshold=z_threshold,
                                            min_n=min_n_points,
                                        )
                                    else:
                                        anomalies = detect_global(
                                            all_traj,
                                            threshold=z_threshold,
                                        )

                                    st.markdown("### 检测结果")
                                    st.markdown(summarize_anomalies(anomalies))

                                    if len(anomalies) > 0:
                                        st.markdown(
                                            f"**异常明细（共 {len(anomalies)} 条，"
                                            f"影响 {anomalies['vessel_id'].nunique()} 艘船）**"
                                        )
                                        display_cols = {
                                            "vessel_id": "船 ID",
                                            "time": "时间",
                                            "sog": "航速(kn)",
                                            "z_score": "Z-Score",
                                            "sog_mean": "均值(kn)",
                                            "sog_std": "σ(kn)",
                                            "anomaly_type": "异常类型",
                                        }
                                        show_df = anomalies[
                                            list(display_cols.keys())
                                        ].rename(columns=display_cols)
                                        show_df["时间"] = pd.to_datetime(
                                            show_df["时间"]
                                        ).dt.strftime("%Y-%m-%d %H:%M")
                                        show_df["Z-Score"] = show_df["Z-Score"].apply(
                                            lambda x: f"{x:+.1f}"
                                        )
                                        show_df["航速(kn)"] = show_df["航速(kn)"].round(1)
                                        show_df["均值(kn)"] = show_df["均值(kn)"].round(1)
                                        show_df["σ(kn)"] = show_df["σ(kn)"].round(1)
                                        st.dataframe(
                                            show_df,
                                            use_container_width=True,
                                            hide_index=True,
                                        )

                                        # 在地图上高亮异常点
                                        st.markdown("**地图视图（红色 = 异常点）**")
                                        lat_center = float(all_traj["lat"].mean())
                                        lon_center = float(all_traj["lon"].mean())
                                        anomaly_points = anomalies[
                                            ["vessel_id", "time", "lat", "lon", "sog"]
                                        ].copy()
                                        anomaly_points["position"] = anomaly_points.apply(
                                            lambda r: [float(r["lon"]), float(r["lat"])],
                                            axis=1,
                                        )
                                        # 按船着色
                                        palette = [
                                            [255, 60, 60], [60, 140, 255], [60, 200, 100],
                                            [255, 160, 0], [160, 60, 255], [0, 220, 200],
                                            [255, 100, 150], [100, 100, 255], [200, 200, 0],
                                            [0, 200, 200],
                                        ]
                                        vessel_ids_in_anomaly = sorted(
                                            anomalies["vessel_id"].unique().tolist()
                                        )
                                        vessel_colors = {
                                            vid: palette[i % len(palette)]
                                            for i, vid in enumerate(vessel_ids_in_anomaly)
                                        }
                                        anomaly_points["color"] = anomaly_points[
                                            "vessel_id"
                                        ].map(vessel_colors)
                                        anomaly_scatter = []
                                        for _, r in anomaly_points.iterrows():
                                            anomaly_scatter.append({
                                                "position": r["position"],
                                                "color": r["color"],
                                                "label": (
                                                    f"船 {int(r['vessel_id'])} "
                                                    f"{pd.Timestamp(r['time']).strftime('%H:%M')} "
                                                    f"{r['sog']:.1f}kn"
                                                ),
                                            })
                                        deck_anomaly = _safe_deck(
                                            layers=[
                                                pdk.Layer(
                                                    "ScatterplotLayer",
                                                    data=anomaly_scatter,
                                                    get_position="position",
                                                    get_fill_color="color",
                                                    get_radius=3000,
                                                    get_line_width=200,
                                                    get_line_color=[255, 255, 255, 200],
                                                    pickable=True,
                                                ),
                                            ],
                                            map_style="dark",
                                            initial_view_state=pdk.ViewState(
                                                latitude=lat_center,
                                                longitude=lon_center,
                                                zoom=10,
                                                pitch=40,
                                            ),
                                            height=420,
                                            tooltip={
                                                "html": "<b>{label}</b>",
                                                "style": {"color": "white", "font-size": "12px"},
                                            },
                                        )
                                        st.pydeck_chart(
                                            deck_anomaly, use_container_width=True
                                        )
                            except Exception as e:
                                st.error(f"检测失败：{e}")
                                with st.expander("完整错误栈", expanded=False):
                                    st.code(traceback.format_exc(), language="python")

            # ---- 地理围栏 ----
            if active_ais_tab == "??? ????":
                render_fence_page(ais_query, registry, RESTRICTED_ZONES, _safe_deck)

            # ---- 自然语言查询 ----
            if active_ais_tab == "自然语言查询":
                st.markdown(
                    "**自然语言查询 AIS 数据** — 输入问题，系统由大模型解析意图并自动调用 AIS 查询工具。"
                )
                if ais_agent is not None and ais_agent.has_llm():
                    st.success("已启用 AI 智能查询（Function Calling）")
                else:
                    st.warning(
                        "未配置 LLM_API_KEY，已使用关键词匹配降级方案。"
                        "请在 .env 中配置 DeepSeek API Key 后重启 demo。"
                    )

                st.info(
                    "💡 **本 Tab 用于查具体船只的 AIS 数据（Function Calling 路径）。**\n\n"
                    "**查 VTS 概念、规则请切到左边的 \"海事知识库问答\"**"
                )

                st.markdown("**💬 示例问题（点击直接查询）：**")
                nl_examples = [
                    "数据集整体概况是怎样的？",
                    "数据里最快的速度记录是多少节？",
                    "船 18330 的统计摘要",
                    "2020年10月有哪些船活跃？",
                    "停泊率超过50%的船有哪些？",
                    "航行时间最长的船是哪艘？",
                    "什么是 AIS 系统？",
                ]
                ex_cols = st.columns(min(len(nl_examples), 4))
                if "pending_nl_question" not in st.session_state:
                    st.session_state.pending_nl_question = None
                for i, ex in enumerate(nl_examples):
                    if ex_cols[i % 4].button(ex, key=f"nl_ex_{i}", use_container_width=True):
                        st.session_state.pending_nl_question = ex

                nl_query = st.text_input(
                    "或者输入你自己的问题",
                    value="",
                    placeholder="例如：2019年12月有哪些船活跃？",
                )

                # 优先使用按钮触发的示例问题
                question = (
                    st.session_state.pending_nl_question
                    if st.session_state.pending_nl_question
                    else nl_query
                )

                # 按钮触发的示例：立即查询；自定义输入：需要点"查询"按钮
                should_query = bool(
                    (st.session_state.pending_nl_question)
                    or (question and st.button("查询", type="primary", key="nl_query_btn"))
                )

                if should_query and question:
                    st.session_state.pending_nl_question = None
                    with st.spinner("AI 正在解析问题并查询 AIS 数据..."):
                        result = ais_agent.ask(question, chat_history=[])

                    # 展示 AI 最终回答
                    st.markdown("### 🤖 AI 回答")
                    st.markdown(result["answer"])

                    # 展示工具调用细节
                    if result.get("tool_calls"):
                        with st.expander(
                            f"🔧 查看 AI 调用的工具（共 {len(result['tool_calls'])} 次）",
                            expanded=False
                        ):
                            for i, tc in enumerate(result["tool_calls"], start=1):
                                st.markdown(
                                    f"**调用 {i}**: `{tc['name']}`"
                                )
                                st.json(tc["arguments"])
                                st.caption("返回数据：")
                                st.code(
                                    str(tc["result"])[:1500]
                                    + (" ...[已截断]" if len(str(tc["result"])) > 1500 else ""),
                                    language="json",
                                )
                                st.divider()

    # ==========================
    # Tab 3: 风险研判
    # ==========================
    if active_main_tab == "船舶风险研判":
        st.subheader("船舶风险研判")
        st.write("输入船舶当前状态，系统会根据简单 Demo 规则输出风险等级、原因和建议。")

        col1, col2, col3 = st.columns(3)
        with col1:
            speed = st.number_input("船舶航速 speed（节）",
                                    min_value=0.0, max_value=40.0, value=1.2, step=0.1)
        with col2:
            distance = st.number_input("距离限制区域（海里）",
                                       min_value=0.0, max_value=20.0, value=0.3, step=0.1)
        with col3:
            course_change = st.number_input("短时间航向变化（度）",
                                            min_value=0.0, max_value=180.0, value=45.0, step=1.0)

        if st.button("开始风险研判", type="primary"):
            risk_result = judge_vessel_risk(
                speed=speed,
                distance_to_restricted_area=distance,
                course_change=course_change,
            )
            st.markdown("### 风险研判结果")
            col_r1, col_r2 = st.columns(2)
            with col_r1:
                st.metric("风险等级", risk_result["risk_level"])
            with col_r2:
                st.metric("风险分数", risk_result["score"])

            st.markdown("#### 判断原因")
            for reason in risk_result["reasons"]:
                st.write(f"- {reason}")

            st.markdown("#### 处置建议")
            for suggestion in risk_result["suggestions"]:
                st.write(f"- {suggestion}")

            st.warning(risk_result["disclaimer"])

    # ==========================
    # Tab 4: 渔场热力图
    # ==========================
    if active_main_tab == "📊 渔场热力图":
        st.subheader("📊 渔场密度热力图")
        st.write("基于 AIS 航迹点密度生成热力图，低速聚集区域（可能的渔场）以深红色高亮显示。")

        if "ais_data" not in st.session_state or st.session_state.ais_data is None:
            st.warning("请先在「AIS 轨迹分析」中加载船只数据。")
        else:
            ais_df = st.session_state.ais_data

            # ① 权重计算：低速点权重更高
            col_w1, col_w2 = st.columns([1, 1])
            with col_w1:
                st.session_state.heatmap_low_speed = st.slider(
                    "低速阈值（节）——此速度以下视为可能作业",
                    min_value=0.0, max_value=10.0,
                    value=3.0, step=0.1,
                    key="hm_low_speed",
                )
            with col_w2:
                st.session_state.heatmap_high_weight = st.slider(
                    "低速点权重倍数",
                    min_value=1.0, max_value=10.0,
                    value=3.0, step=0.1,
                    key="hm_high_weight",
                )

            # ② 热力图数据准备
            low_thresh = st.session_state.get("heatmap_low_speed", 3.0)
            high_weight = st.session_state.get("heatmap_high_weight", 3.0)

            heatmap_df = ais_df[["lon", "lat"]].copy()
            # 速度列可能不存在或为 NaN，默认给一个正常速度以避免权重异常
            if "sog" in ais_df.columns:
                heatmap_df["weight"] = ais_df["sog"].fillna(5.0).apply(
                    lambda s: high_weight if s < low_thresh else 1.0
                )
            else:
                heatmap_df["weight"] = 1.0

            # ③ 禁航区域边界（叠加在热力图上）—— 展示所有预定义区域 + 自定义区域
            custom_zones = getattr(st.session_state, "custom_zones", [])
            all_zones = list(RESTRICTED_ZONES) + list(custom_zones)
            zone_boundary_data = []
            zone_label_data = []
            for z in all_zones:
                if z.get("type") == "circle":
                    # 用 36 边形近似圆
                    import math
                    n_pts = 36
                    pts = []
                    center_lon, center_lat = z["lon"], z["lat"]
                    radius_deg = z["radius_nm"] / 60.0  # 海里转纬度
                    for k in range(n_pts):
                        angle = 2 * math.pi * k / n_pts
                        pt_lon = center_lon + radius_deg * math.cos(angle) / math.cos(math.radians(center_lat))
                        pt_lat = center_lat + radius_deg * math.sin(angle)
                        pts.append([float(pt_lon), float(pt_lat)])
                    pts.append(pts[0])
                    zone_boundary_data.append({
                        "path": pts,
                        "color": [0, 100, 200, 180],
                        "width": 300,
                        "label": z["name"],
                    })
                    zone_label_data.append({
                        "position": [float(z["lon"]), float(z["lat"])],
                        "text": z["name"],
                    })
                else:
                    lat_min, lat_max = z.get("lat_min", 0), z.get("lat_max", 0)
                    lon_min, lon_max = z.get("lon_min", 0), z.get("lon_max", 0)
                    rect = [
                        [float(lon_min), float(lat_min)],
                        [float(lon_max), float(lat_min)],
                        [float(lon_max), float(lat_max)],
                        [float(lon_min), float(lat_max)],
                        [float(lon_min), float(lat_min)],
                    ]
                    zone_boundary_data.append({
                        "path": rect,
                        "color": [0, 100, 200, 180],
                        "width": 300,
                        "label": z["name"],
                    })
                    zone_label_data.append({
                        "position": [(float(lon_min) + float(lon_max)) / 2,
                                     (float(lat_min) + float(lat_max)) / 2],
                        "text": z["name"],
                    })

            # ④ 地图中心
            map_lat = float(ais_df["lat"].mean())
            map_lon = float(ais_df["lon"].mean())

            layers = [
                # HeatmapLayer
                pdk.Layer(
                    "HeatmapLayer",
                    data=heatmap_df,
                    get_position="[lon, lat]",
                    get_weight="weight",
                    radius_pixels=70,
                    intensity=1.2,
                    threshold=0.03,
                    color_range=[
                        [255, 255, 178],
                        [254, 204, 92],
                        [253, 141, 60],
                        [240, 59, 32],
                        [189, 0, 38],
                    ],
                    pickable=False,
                ),
                # 禁航区域轮廓（PathLayer）
                pdk.Layer(
                    "PathLayer",
                    data=zone_boundary_data,
                    get_width="width",
                    get_color="color",
                    pickable=True,
                ),
            ]

            deck = _safe_deck(
                layers=layers,
                initial_view_state=pdk.ViewState(
                    latitude=map_lat,
                    longitude=map_lon,
                    zoom=9,
                    pitch=30,
                ),
                height=550,
                tooltip={"html": "<b>{label}</b>", "style": {"color": "white"}},
            )
            st.pydeck_chart(deck, use_container_width=True)

            # ⑤ 颜色图例
            st.markdown("""
            <div style="display:flex;align-items:center;gap:8px;font-size:13px;margin-top:4px;">
                <span>密度：</span>
                <span style="background:#ffffb2;padding:2px 10px;border-radius:3px;">低</span>
                <span style="background:#fecc5c;padding:2px 10px;border-radius:3px;">中低</span>
                <span style="background:#fd8d3c;padding:2px 10px;border-radius:3px;">中</span>
                <span style="background:#f03b20;padding:2px 10px;border-radius:3px;">中高</span>
                <span style="background:#bd0026;color:#fff;padding:2px 10px;border-radius:3px;">高（渔场聚集区）</span>
                &nbsp;|&nbsp;
                <span style="color:#0064c8;">━</span>&nbsp;禁航区边界
            </div>
            """, unsafe_allow_html=True)

            # ⑥ 统计摘要
            low_speed_count = int((ais_df["sog"].fillna(5.0) < low_thresh).sum()) if "sog" in ais_df.columns else 0
            total_count = len(ais_df)
            st.caption(
                f"共 {total_count} 条 AIS 航迹点，"
                f"其中 {low_speed_count} 条为低速（< {low_thresh} 节），"
                f"权重 ×{high_weight}。"
            )

    # ==========================
    # Tab 5: Demo 说明
    # ==========================
    if active_main_tab == "Demo 说明":
        st.subheader("Demo 说明")
        st.markdown(
            """
            本 Demo 展示了一个扩展版 VTS 海事智能体原型。
            已对接 DeepSeek 大模型（OpenAI 兼容协议）。

            ### 当前已实现能力

            1. **海事知识库问答**（RAG + LLM 流式输出）
               - 读取 `data/` 文件夹中的海事文档；
               - 将文档切分成 chunk 并向量化；
               - 根据用户问题检索相关片段，由 DeepSeek 流式生成回答。

            2. **AIS 轨迹分析**
               - 加载 100 艘渔船的 AIS 历史轨迹数据（共 131,907 个数据点）；
               - 单船轨迹查询与统计摘要（航速/航向/停泊率/航程估算）；
               - 多船联合对比分析；
               - **自然语言查询（LLM Function Calling）**：DeepSeek 自动解析用户问题，
                 选择合适工具（list_vessels / vessel_summary / vessels_by_month /
                 vessels_by_area / vessels_by_time / dataset_overview / compare_vessels）
                 并返回结构化结果。

            3. **简单风险研判**
               - 根据航速、限制区域距离、航向变化进行规则判断。

            ### 数据特点

            - 船只 ID 范围：18330 ~ 18429（100 艘船）
            - 时间跨度：2016-11 ~ 2020-11
            - 主要海域：东海长江口 / 舟山渔场（31°N, 124°E 附近）
            - 采样间隔：统一 10 分钟

            ### 当前版本限制

            - 风险规则是 Demo 规则，不代表真实海事监管阈值；
            - 地图可视化需要安装 pydeck / folium 等地图库；
            - 当前没有接入实时 AIS 数据流；
            - 后续可扩展：真实地图可视化、禁航区地理围栏检测、
              轨迹异常检测、LangGraph 多智能体工作流。

            ### 配置说明

            在项目根目录的 `.env` 文件中配置：
            ```
            LLM_API_KEY=<你的 DeepSeek API Key>
            LLM_BASE_URL=https://api.deepseek.com/v1
            LLM_MODEL=deepseek-chat
            ```
            配置后需重启 demo。未配置时系统自动回退到本地检索结果。
            """
        )


if __name__ == "__main__":
    main()
