"""Entry point for Streamlit Community Cloud."""
from __future__ import annotations

import os
import runpy
from pathlib import Path

os.environ["STOCK_AI_CLOUD"] = "1"
os.environ.setdefault("STOCK_AI_DATA_DIR", "/tmp/stock_ai_cloud_runtime")
runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
