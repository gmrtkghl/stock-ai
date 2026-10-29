"""Streamlit Community Cloud entry point for the v12 mobile hotfix."""
from __future__ import annotations

import os
import runpy
from pathlib import Path

os.environ["STOCK_AI_CLOUD"] = "1"
os.environ.setdefault("STOCK_AI_DATA_DIR", "/tmp/stock_ai_cloud_runtime")
runpy.run_path(str(Path(__file__).with_name("app_v12_fixed.py")), run_name="__main__")
