# YomiScan development instructions

- YomiScan is offline-first. Prefer local, open-source components; avoid paid APIs and cloud OCR.
- Implement only the explicitly requested phase. OCR, morphological analysis, and local
  JMdict lookup, local sentence translation, localhost FastAPI, and Chrome study-mode
  selection/popup, single-page text detection/analysis, and conservative single-page
  masking/inpainting/typesetting are implemented. Chapter translation, browser page
  replacement, OCR correction, and JLPT grading remain future work.
- Keep components modular with small typed interfaces; avoid premature abstractions.
- Use Python type hints and useful tests. Ordinary tests must not download or load OCR, translation, or detection weights.
- Do not hide failures with broad exception handling. At third-party boundaries, wrap failures
  with actionable context and preserve the exception cause.
- Preserve Windows compatibility and cross-platform paths.
- Keep Python >=3.13,<3.14 unless an actual dependency incompatibility requires a change.
- Use uv and pyproject.toml, keep uv.lock, and do not install dependencies globally.
- Benchmark technologies on representative samples before major architectural commitments.
- Never commit copyrighted manga samples, local model weights, or caches.
- Keep downloaded dictionaries and generated SQLite databases out of Git. Preserve JMdict
  and UniDic attribution; their data is not covered by YomiScan's MIT license.
- Validate with uv run pytest and package import checks. Report real inference separately
  from mocked unit tests; never claim OCR accuracy without running actual images.
