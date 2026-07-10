import re
from typing import Dict, Any, List, Optional, Generator

from openai import OpenAI

from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from src.prompts import SYSTEM_PROMPT, RAG_USER_TEMPLATE, GENERAL_USER_TEMPLATE
from src.vector_store import SimpleVectorStore


class RAGEngine:
    # 相似度阈值：低于此值时，认为知识库无相关内容，退回大模型自身知识
    # 0.35 适配 paraphrase-multilingual-MiniLM-L12-v2 对中英文语义的常见分数区间（通常 0.35–0.75）
    RETRIEVAL_THRESHOLD = 0.35

    # 知识库核心关键词：当用户问题包含其中任一关键词时，
    # 强制走 RAG 路径（即使最高相似度未达阈值）。
    # 解决 paraphrase-multilingual-MiniLM-L12-v2 对短查询打分偏低的问题。
    KB_KEYWORDS = frozenset([
        "VTS", "vts", "船舶交通",
        "AIS", "ais", "自动识别",
        "IMO", "imo", "国际海事",
        "IALA", "iala",
        "VTMS", "vtms", "VTMIS", "vtmis",
        "VHF", "vhf", "雷达", "radar",
        "CCTV",
        "ECDIS", "ecdis",
        "LRIT", "lrit",
        "COLREG", "colreg", "避碰规则", "避碰",
        "MMSI", "mmsi",
        "静态", "动态", "航速", "航向", "船位",
        "异常", "静默", "偏航", "侵入", "关闭",
        "风险", "事故", "碰撞", "搁浅", "失控",
        "风险规则", "异常行为",
        "港口", "航道", "锚地", "禁航", "安全区",
        "主管机关", "VTS 区域", "VTS 中心",
        "海事", "航运", "船舶",
        # 常见船只问法
        "渔船", "货船", "油船", "客船", "拖轮", "散货船", "集装箱船",
        "是什么样的", "概况", "摘要", "航行记录",
        "数据点", "航速统计", "活动范围", "停泊",
        "航行时长", "总航程", "航向", "经纬度", "航行摘要",
        "渔船", "船只",
    ])

    @classmethod
    def _has_kb_keyword(cls, text: str) -> bool:
        """检查问题文本是否包含知识库核心关键词。"""
        if not text:
            return False
        for kw in cls.KB_KEYWORDS:
            if kw in text:
                return True
        return False

    @classmethod
    def _has_vessel_id(cls, text: str, vessel_ids: Optional[List[int]]) -> bool:
        """检查问题文本是否包含知识库已知的船只 ID，命中则强制 RAG。"""
        if not vessel_ids or not text:
            return False
        vid_pattern = re.compile(r"\b(\d{4,7})\b")
        for m in vid_pattern.finditer(text):
            if int(m.group(1)) in vessel_ids:
                return True
        return False

    @classmethod
    def _extract_vessel_ids(cls, text: str, vessel_ids: Optional[List[int]]) -> List[int]:
        """从问题中提取已知船只 ID，保持用户输入顺序并去重。"""
        if not vessel_ids or not text:
            return []

        known = set(vessel_ids)
        found: List[int] = []
        vid_pattern = re.compile(r"\b(\d{4,7})\b")
        for m in vid_pattern.finditer(text):
            vid = int(m.group(1))
            if vid in known and vid not in found:
                found.append(vid)
        return found

    def __init__(self, vector_store: SimpleVectorStore):
        self.vector_store = vector_store
        self._client: Optional[OpenAI] = None

    def _build_context(self, retrieved_results) -> str:
        """
        将检索到的文档片段拼接成上下文。
        """
        context_parts = []

        for rank, (score, chunk) in enumerate(retrieved_results, start=1):
            context_parts.append(
                f"[片段 {rank} | 来源: {chunk.doc_name} | chunk_id: {chunk.chunk_id} | 相似度: {score:.3f}]\n"
                f"{chunk.text}"
            )

        return "\n\n".join(context_parts)

    def _retrieve(
        self,
        question: str,
        top_k: int,
        vessel_ids: Optional[List[int]] = None,
    ) -> List[tuple]:
        """
        混合检索：
        - 如果问题中出现已知船号，先精确召回对应 AIS 知识文件；
        - 再用向量检索补充其他相关片段。

        这样可以避免 embedding 把 18330 这类纯数字船号检索到相近但错误的船。
        """
        exact_results: List[tuple] = []
        matched_ids = self._extract_vessel_ids(question, vessel_ids)
        if matched_ids:
            target_docs = {f"ais_knowledge/vessel_{vid}.txt" for vid in matched_ids}
            for chunk in self.vector_store.chunks:
                if chunk.doc_name in target_docs:
                    exact_results.append((1.0, chunk))

        semantic_results = self.vector_store.retrieve(question, top_k=top_k)

        merged: List[tuple] = []
        seen = set()
        for score, chunk in exact_results + semantic_results:
            key = (chunk.doc_name, chunk.chunk_id)
            if key in seen:
                continue
            seen.add(key)
            merged.append((score, chunk))
            if len(merged) >= top_k:
                break

        return merged

    def _fallback_answer(self, question: str, context: str) -> str:
        """
        如果没有配置大模型 API Key，就返回一个本地 fallback 结果。
        这样项目即使没有 API Key，也能展示 RAG 检索效果。
        """
        return (
            "当前未配置 LLM_API_KEY，因此仅展示知识库检索结果。\n\n"
            f"【用户问题】\n{question}\n\n"
            f"【检索到的相关知识片段】\n{context}\n\n"
            "你可以配置 .env 文件中的 LLM_API_KEY，让系统调用大模型生成自然语言回答。"
        )

    def _build_client(self) -> Optional[OpenAI]:
        """
        根据配置构建 OpenAI 客户端；未配置 API Key 时返回 None。
        客户端实例被缓存，避免每次调用都重新建立连接。
        """
        if not LLM_API_KEY:
            return None

        if self._client is not None:
            return self._client

        client_kwargs = {"api_key": LLM_API_KEY}
        if LLM_BASE_URL:
            client_kwargs["base_url"] = LLM_BASE_URL
        self._client = OpenAI(**client_kwargs)
        return self._client

    @staticmethod
    def is_llm_available() -> bool:
        """静态方法：判断当前是否配置了可用的 LLM。"""
        return bool(LLM_API_KEY)

    @staticmethod
    def llm_info() -> dict:
        """返回当前 LLM 配置信息，供前端展示。"""
        return {
            "available": bool(LLM_API_KEY),
            "model": LLM_MODEL,
            "base_url": LLM_BASE_URL or "(default OpenAI)",
            "api_key_preview": (LLM_API_KEY[:7] + "..." + LLM_API_KEY[-4:])
            if LLM_API_KEY else "(未配置)",
        }

    def get_llm_info(self) -> dict:
        """实例方法版本：与静态方法等价，但走实例属性查找，
        可避免 Streamlit 多进程/类对象缓存带来的 AttributeError。"""
        return self.llm_info()

    def has_llm(self) -> bool:
        """实例方法版本。"""
        return self.is_llm_available()

    def _classify_retrieval_quality(
        self, retrieved_results: List[tuple], question: str = "",
        vessel_ids: Optional[List[int]] = None
    ) -> tuple[str, Optional[str]]:
        """
        判断检索质量，返回 (mode, context_or_None)。
        - mode == "rag": 知识库有相关内容，context 有效
        - mode == "general": 知识库无相关内容，退回大模型自身知识

        决策规则（先后顺序）：
        1. 没有检索到任何片段 → general
        2. 问题包含知识库核心关键词 → 强制 rag（绕过相似度阈值）
        3. 问题包含已知船只 ID → 强制 rag
        4. 最高相似度 >= 阈值 → rag
        5. 否则 → general
        """
        if not retrieved_results:
            return "general", None

        # 关键词命中兜底：解决 embedding 模型对短查询打分偏低的问题
        if self._has_kb_keyword(question):
            return "rag", self._build_context(retrieved_results)

        # 船只 ID 命中兜底：用户问具体船只时强制走 RAG
        if self._has_vessel_id(question, vessel_ids):
            return "rag", self._build_context(retrieved_results)

        max_score = retrieved_results[0][0]  # 已按相似度降序排列
        if max_score < self.RETRIEVAL_THRESHOLD:
            return "general", None

        return "rag", self._build_context(retrieved_results)

    def _format_sources(self, retrieved_results) -> List[Dict[str, Any]]:
        """
        将检索结果整理成前端容易展示的格式。
        """
        sources = []

        for score, chunk in retrieved_results:
            sources.append(
                {
                    "score": round(score, 3),
                    "doc_name": chunk.doc_name,
                    "chunk_id": chunk.chunk_id,
                    "text": chunk.text,
                    "source_type": chunk.source_type,
                }
            )

        return sources

    def _build_messages(
        self,
        question: str,
        mode: str,
        context: Optional[str],
        chat_history: Optional[List[Dict[str, str]]],
    ) -> List[Dict[str, str]]:
        """构建发送给 LLM 的 messages 列表。"""
        messages: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        if chat_history:
            messages.extend(chat_history)

        if mode == "rag":
            user_prompt = RAG_USER_TEMPLATE.format(
                context=context, question=question
            )
        else:
            user_prompt = GENERAL_USER_TEMPLATE.format(question=question)

        messages.append({"role": "user", "content": user_prompt})
        return messages

    def ask(
        self,
        question: str,
        top_k: int = 4,
        chat_history: Optional[List[Dict[str, str]]] = None,
        vessel_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """
        RAG 问答题函数（非流式，向后兼容旧调用）。

        Hybrid 策略：
        - 知识库检索质量高（最高相似度 >= RETRIEVAL_THRESHOLD）
          → 基于知识库片段回答
        - 知识库无相关内容（最高相似度 < RETRIEVAL_THRESHOLD）
          → 退回大模型自身知识回答，并标注来源
        """
        retrieved_results = self._retrieve(question, top_k=top_k, vessel_ids=vessel_ids)
        mode, context = self._classify_retrieval_quality(
            retrieved_results, question, vessel_ids
        )

        client = self._build_client()
        if client is None:
            if mode == "rag":
                return {
                    "answer": self._fallback_answer(question, context),
                    "sources": self._format_sources(retrieved_results),
                    "retrieval_mode": "rag",
                }
            return {
                "answer": (
                    "当前未配置 LLM_API_KEY，无法生成回答。"
                    "请在 .env 中配置 API Key 后重试。"
                ),
                "sources": [],
                "retrieval_mode": "general",
            }

        messages = self._build_messages(question, mode, context, chat_history)

        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.2,
        )

        answer = response.choices[0].message.content

        # 知识库无相关内容时，在答案开头追加标注
        if mode == "general":
            answer = (
                "📚 知识库中未找到相关内容，以下回答基于大模型通用知识：\n\n"
                + answer
            )

        return {
            "answer": answer,
            "sources": self._format_sources(retrieved_results) if mode == "rag" else [],
            "retrieval_mode": mode,
        }

    def stream_ask(
        self,
        question: str,
        top_k: int = 4,
        chat_history: Optional[List[Dict[str, str]]] = None,
        vessel_ids: Optional[List[int]] = None,
    ) -> Generator[str, None, Dict[str, Any]]:
        """
        流式 RAG 问答。

        Hybrid 策略（与 ask 一致）：
        - 高相似度 → RAG 路径
        - 低相似度 → 大模型自身知识路径

        返回一个生成器，每次 yield 一段 LLM 输出文本。
        生成器最终 return 一个 dict，包含完整答案和 sources（供前端缓存展示）。
        """
        retrieved_results = self._retrieve(question, top_k=top_k, vessel_ids=vessel_ids)
        mode, context = self._classify_retrieval_quality(
            retrieved_results, question, vessel_ids
        )

        sources = self._format_sources(retrieved_results) if mode == "rag" else []
        final_payload: Dict[str, Any] = {
            "sources": sources,
            "retrieval_mode": mode,
        }

        client = self._build_client()
        if client is None:
            if mode == "rag":
                answer = self._fallback_answer(question, context)
                final_payload["answer"] = answer
                yield answer
                return final_payload
            answer = (
                "当前未配置 LLM_API_KEY，无法生成回答。"
                "请在 .env 中配置 API Key 后重试。"
            )
            final_payload["answer"] = answer
            yield answer
            return final_payload

        messages = self._build_messages(question, mode, context, chat_history)

        try:
            if mode == "general":
                yield "📚 知识库中未找到相关内容，以下回答基于大模型通用知识：\n\n"

            stream = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=0.2,
                stream=True,
            )

            collected: List[str] = []
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    collected.append(delta)
                    yield delta

            final_payload["answer"] = "".join(collected)
            return final_payload
        except Exception as e:
            err_answer = f"⚠️ LLM 调用失败：{e}"
            final_payload["answer"] = err_answer
            yield err_answer
            return final_payload
