#!/usr/bin/env python3
"""Stage-2: compute the batch receipt epoch from all extracted states, then run
the pure decision function over every case. Instant — no OCR."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mib.pipeline import FALLBACKS, batch_epoch, decide  # noqa: E402


def main(states_glob_dir, pred_out, detail_out):
    states = []
    for path in sorted(Path(states_glob_dir).glob("state*.jsonl")):
        for line in open(path):
            states.append(json.loads(line))

    epoch = batch_epoch(states)
    print(f"batch epoch: {epoch} over {len(states)} cases")

    with open(pred_out, "w") as pf, open(detail_out, "w") as df:
        for state in states:
            try:
                pred, detail = decide(state, epoch)
            except Exception as exc:
                pred = {"case_id": state["case_id"], **FALLBACKS,
                        "adjudication": "NEEDS_REVIEW", "confidence": 0.3}
                detail = {"error": repr(exc)[:200]}
            pf.write(json.dumps(pred) + "\n")
            df.write(json.dumps({"case_id": pred["case_id"], **detail}) + "\n")


if __name__ == "__main__":
    main(*sys.argv[1:4])
