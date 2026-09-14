"""Run the real app with deterministic retrieval and no external model calls.

AIS loading, RAGEngine, page routing, monthly calculations and document exporters
are real. Only embedding initialization/retrieval is replaced for offline tests.
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ['LLM_API_KEY'] = ''
os.environ['VTS_HF_CACHE_DIR'] = str(ROOT / '.cache' / 'tests')

# The existing app patches stderr on import; retain the test runner's capture.
stderr_write, stderr_flush = sys.stderr.write, sys.stderr.flush
try:
    import app
finally:
    sys.stderr.write, sys.stderr.flush = stderr_write, stderr_flush

import src.ais_agent as ais_agent_module
import src.rag_engine as rag_engine_module

chunks = app.build_chunks(app.DATA_DIR)
store = SimpleNamespace(
    chunks=chunks,
    retrieve=lambda question, top_k=4: [(0.9, chunk) for chunk in chunks[:top_k]],
)
real_download_button = st.download_button


def capture_download(label, data, **kwargs):
    downloads = dict(st.session_state.get('test_downloads', {}))
    downloads[kwargs['key']] = bytes(data)
    st.session_state.test_downloads = downloads
    return real_download_button(label, data, **kwargs)


with (
    patch.object(app, 'load_vector_store', return_value=store),
    patch.object(ais_agent_module, 'LLM_API_KEY', ''),
    patch.object(rag_engine_module, 'LLM_API_KEY', ''),
    patch.object(st, 'download_button', side_effect=capture_download),
):
    if st.session_state.get('test_report_direct', False):
        _, query = app.load_ais()
        app.render_monthly_report_page(
            query, app.RESTRICTED_ZONES, app._calc_monthly_vessel_rows,
            app.build_monthly_report_text, app._cached_report_docx_bytes,
            app._cached_report_pdf_bytes,
        )
    else:
        app.main()
