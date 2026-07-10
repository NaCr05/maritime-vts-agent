from typing import List, Tuple, TYPE_CHECKING
import re
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from src.document_loader import DocumentChunk

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


def _patch_tqdm():
    """Patch tqdm before sentence_transformers imports it."""
    import os as _os
    _os.environ["TQDM_DISABLE"] = "1"
    import sys as _sys
    import types as _types
    import importlib.util

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
            if fullname in _sys.modules:
                return importlib.util.find_spec(fullname)
            return None
        def create_module(self, spec): return None
        def exec_module(self, module): pass
        @staticmethod
        def find_module(fullname, path=None):
            if fullname in _sys.modules:
                return _FakeLoader()
            return None

    class _AutoModule(_types.ModuleType):
        def __init__(self, name):
            super().__init__(name)
            self.__path__ = []
        def __getattr__(self, attr: str):
            if attr.startswith('_'):
                raise AttributeError(attr)
            child_name = f"{self.__name__}.{attr}"
            child = _AutoModule(child_name)
            _sys.modules[child_name] = child
            setattr(self, attr, child)
            return child
        def load_module(self, fullname):
            return _sys.modules.get(fullname)

    def _make_fake_tqdm():
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
        return _fake_tqdm

    class _FakeSpec:
        def __init__(self, name):
            self.name = name
            self.origin = None
            self.submodule_search_locations = []
            self.parent = name.rsplit('.', 1)[0] if '.' in name else ''

    _fake_tqdm = _make_fake_tqdm()

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


class SimpleVectorStore:
    """
    一个极简版向量库。
    用 sentence-transformers 生成 embedding，
    用 cosine similarity 做语义检索。

    真实工程中可以替换成 Chroma、FAISS、Milvus 等。
    """

    def __init__(self, model_name: str):
        _patch_tqdm()
        self.model_name = model_name
        from sentence_transformers import SentenceTransformer
        self.model: "SentenceTransformer" = SentenceTransformer(model_name, device='cpu')
        self.chunks: List[DocumentChunk] = []
        self.embeddings = None

    def build(self, chunks: List[DocumentChunk]) -> None:
        """
        为所有 chunk 构建向量。
        """
        self.chunks = chunks

        texts = [chunk.text for chunk in chunks]

        if not texts:
            self.embeddings = np.array([])
            return

        self.embeddings = self.model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True
        )

    def retrieve(self, query: str, top_k: int = 4) -> List[Tuple[float, DocumentChunk]]:
        """
        根据用户问题检索最相关的 top_k 个 chunk。
        返回：
        [
            (相似度分数, DocumentChunk),
            ...
        ]
        """
        if self.embeddings is None or len(self.chunks) == 0:
            return []

        exact_results: List[Tuple[float, DocumentChunk]] = []
        vessel_ids = []
        for match in re.finditer(r"\b(\d{4,7})\b", query or ""):
            vid = match.group(1)
            if vid not in vessel_ids:
                vessel_ids.append(vid)

        if vessel_ids:
            target_docs = {f"ais_knowledge/vessel_{vid}.txt" for vid in vessel_ids}
            for chunk in self.chunks:
                if chunk.doc_name in target_docs:
                    exact_results.append((1.0, chunk))

        query_embedding = self.model.encode(
            [query],
            convert_to_numpy=True,
            normalize_embeddings=True
        )

        scores = cosine_similarity(query_embedding, self.embeddings)[0]
        top_indices = scores.argsort()[::-1][:top_k]

        results = []
        seen = set()

        for score, chunk in exact_results:
            key = (chunk.doc_name, chunk.chunk_id)
            if key not in seen:
                seen.add(key)
                results.append((score, chunk))

        for idx in top_indices:
            chunk = self.chunks[idx]
            key = (chunk.doc_name, chunk.chunk_id)
            if key in seen:
                continue
            seen.add(key)
            results.append((float(scores[idx]), chunk))
            if len(results) >= top_k:
                break

        return results
