from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple, Optional


@dataclass
class DocumentChunk:
    doc_name: str
    chunk_id: int
    text: str
    source_type: str = "maritime_doc"


def load_text_files(data_dir: Path, prefix: str = "") -> dict:
    """
    读取 data 文件夹下的所有 .txt 文件。
    返回格式：
    {
        "ais_intro.txt": "文本内容",   # prefix="" 时
        "ais_knowledge/vessel_18330.txt": "...",  # prefix="ais_knowledge/" 时
        ...
    }
    """
    documents = {}

    if not data_dir.exists():
        raise FileNotFoundError(f"data folder not found: {data_dir}")

    for file_path in data_dir.glob("*.txt"):
        text = file_path.read_text(encoding="utf-8").strip()
        if text:
            doc_name = f"{prefix}{file_path.name}" if prefix else file_path.name
            documents[doc_name] = text

    return documents


def split_text(text: str, chunk_size: int = 450, overlap: int = 80) -> List[str]:
    """
    将长文本切分成小文本块。
    这里用字符数切分，适合中英文混合的简单 Demo。
    """
    if not text:
        return []

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - overlap
        if start < 0:
            start = 0

        if start >= len(text):
            break

    return chunks


def build_chunks(
    data_dir: Path,
    extra_dirs: Optional[List[Tuple[Path, str]]] = None,
) -> List[DocumentChunk]:
    """
    读取 data 文件夹中的文档，并切分成 DocumentChunk。

    Args:
        data_dir: 主数据目录（如 data/）
        extra_dirs: 额外目录列表，每项为 (Path, prefix)，prefix 用于区分来源。
            例如：[(data/ais_knowledge, "ais_knowledge/")] 会把
            vessel_18330.txt 记成 doc_name="ais_knowledge/vessel_18330.txt"。

    source_type 规则：
        - doc_name 以 "ais_knowledge/" 开头 → "ais_knowledge"
        - 其他情况 → "maritime_doc"
    """
    documents = load_text_files(data_dir)

    if extra_dirs:
        for extra_path, prefix in extra_dirs:
            if extra_path.exists() and extra_path.is_dir():
                documents.update(load_text_files(extra_path, prefix=prefix))

    all_chunks: List[DocumentChunk] = []

    for doc_name, text in documents.items():
        chunks = split_text(text)
        source_type = "ais_knowledge" if doc_name.startswith("ais_knowledge/") else "maritime_doc"

        for idx, chunk_text in enumerate(chunks):
            all_chunks.append(
                DocumentChunk(
                    doc_name=doc_name,
                    chunk_id=idx,
                    text=chunk_text,
                    source_type=source_type,
                )
            )

    return all_chunks
