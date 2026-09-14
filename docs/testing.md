# Page regression tests

Run from the repository root in a virtual environment:

```text
python -m pip install -r requirements-test.txt
python -m pytest tests -q
```

The six cases exercise the real Streamlit application with AppTest:

- Enter the RAG page, submit a question without an API key, and receive source-backed text.
- Reach the monthly report and geofence pages through their actual navigation selections.
- Generate a report for the largest month in the bundled dataset, both through the full navigation and directly through the injected page callbacks. Verify month boundaries, vessel and row totals, Markdown content, parseable DOCX tables and PDF text, and persistence after rerun.
- Explain that natural-language AIS queries require `LLM_API_KEY`, without claiming a keyword fallback.

`tests/smoke_app.py` substitutes a deterministic retrieval fixture for embedding initialization and retrieval. It still runs the real AIS loader, RAGEngine, page routing, monthly calculations, anomaly/geofence analysis, and document exporters. The fixture forces the API key to be empty; no online LLM or model download is needed.

This suite does not validate embedding quality, first-time model installation, live LLM behavior, map tile availability, or every application page. The dependency file intentionally omits sentence-transformers; use `requirements.txt` to run the unmodified application.

Set `VTS_TEST_OUTPUT_DIR` to a local directory to retain the generated Markdown, Word and PDF report for manual inspection. Generated reports are not committed.
