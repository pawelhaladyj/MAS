# tests/conftest.py
import os, sys
# dodaj katalog projektu (…/mas) na początek PYTHONPATH
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
