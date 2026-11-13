"""Force mock mode BEFORE the app is imported, so tests never call a real LLM.
(load_dotenv does not overwrite variables that are already set.)"""
import os
import sys
from pathlib import Path

os.environ["LLM_PROVIDER"] = "mock"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
