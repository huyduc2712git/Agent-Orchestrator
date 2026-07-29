import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from orchestrator.board import store

for tid in ["tsk-0025", "tsk-0026", "tsk-0024"]:
    print("=" * 60, tid)
    for e in store.list_events(tid):
        if e.kind == "comment" and e.agent in ("banner", "hawkeye", "pepper", "jarvis"):
            print(f"\n--- {e.agent} comment ---\n{e.message[:3500]}\n")
