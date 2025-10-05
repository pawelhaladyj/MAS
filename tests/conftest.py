# tests/conftest.py
import os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

AGENTS = os.path.join(ROOT, "agents")   # ⬅ DODANE
if os.path.isdir(AGENTS) and AGENTS not in sys.path:
    sys.path.insert(0, AGENTS)          # ⬅ DODANE
