try:
    from agents.common.slots import REQUIRED_SLOTS
    print("REQUIRED_SLOTS len =", len(REQUIRED_SLOTS))
    print("first 5:", REQUIRED_SLOTS[:5])
except Exception as e:
    print("IMPORT ERROR:", e)