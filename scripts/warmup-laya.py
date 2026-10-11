"""Prepare the cached Laya checkpoint without scanning or sending Facebook comments."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import laya_classifier

if __name__ == "__main__":
    print("Loading Laya multilingual on CPU...", flush=True)
    laya_classifier._get_agent()
    print(json.dumps(laya_classifier.status(), ensure_ascii=True), flush=True)
