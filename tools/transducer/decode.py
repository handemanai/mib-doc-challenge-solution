#!/usr/bin/env python3
"""Trie-constrained beam decode for the transducer + model-vs-baseline eval.

The decoder can only emit character sequences that are LEGAL field values
(the 144x144 joint-name grammar, the closed vocabularies, SPN-\\d{4} and ISO
date formats). Injection-inertness is structural twice over: the model is not
an instruction follower, and the decode literally cannot output anything
outside the legal value space. Beam score = length-normalized logprob, used
as the accept gate against the rapidfuzz fallback.

    venv-train python tools/transducer/decode.py --model /tmp/mib-transducer
"""
import argparse
import json
import math
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from train import (BOS, EOS, FIELD_TAGS, MAX_SRC, MAX_TGT, PAD,  # noqa: E402
                   Transducer, is_test)
from mib.vocab import PURPOSES, SPECIES, VISAS, WORLDS  # noqa: E402

_MODELS = Path(__file__).resolve().parents[2] / "models"
NAMES = json.loads((_MODELS / "name_vocab.json").read_text())


def build_tries():
    def trie_of(values):
        root = {}
        for v in values:
            node = root
            for ch in v:
                node = node.setdefault(ch, {})
            node["$"] = True
        return root

    dates = None  # handled by format walker below
    return {
        "applicant_name": trie_of(f"{a} {b}" for a in NAMES["first"] for b in NAMES["last"]),
        "species_code": trie_of(SPECIES),
        "home_world": trie_of(WORLDS),
        "visa_class": trie_of(VISAS),
        "declared_purpose": trie_of(PURPOSES),
        "sponsor_id": trie_of([f"SPN-{i:04d}" for i in range(10000)]),
        "arrival_date": dates,
    }


def date_children(prefix):
    """Legal next chars for an ISO date prefix (2025-2027, real month/day)."""
    n = len(prefix)
    if n == 0:
        return {"2"}
    if n == 1:
        return {"0"}
    if n == 2:
        return {"2"}
    if n == 3:
        return set("567")
    if n in (4, 7):
        return {"-"}
    if n == 5:
        return {"0", "1"}
    if n == 6:
        return set("123456789") if prefix[5] == "0" else set("012")
    if n == 8:
        return set("0123")
    if n == 9:
        first = prefix[8]
        if first == "0":
            return set("123456789")
        if first in "12":
            return set("0123456789")
        return set("01")
    return set()


class TrieBeam:
    def __init__(self, model, vocab_itos, device):
        self.model = model
        self.itos = vocab_itos
        self.stoi = {s: i for i, s in enumerate(vocab_itos)}
        self.device = device
        self.tries = build_tries()

    def _legal(self, field, prefix, node):
        if field == "arrival_date":
            ch = date_children(prefix)
            return ch, len(prefix) == 10
        if node is None:
            return set(), False
        return {c for c in node if c != "$"}, "$" in node

    def _advance(self, field, node, ch):
        if field == "arrival_date":
            return None
        return node.get(ch) if node else None

    @torch.no_grad()
    def decode(self, field, src_text, width=5):
        """Returns (best_value or None, normalized_logprob)."""
        v = self.stoi
        src = torch.full((1, MAX_SRC), PAD, dtype=torch.long, device=self.device)
        s = [v[f"<{field}>"]] + [v.get(c, 3) for c in src_text][: MAX_SRC - 1]
        src[0, :len(s)] = torch.tensor(s, device=self.device)
        mem, sm = self.model.encode(src)

        root = self.tries[field]
        beams = [(0.0, "", root, [BOS], False)]  # logp, text, node, ys, done
        for _ in range(MAX_TGT - 1):
            nxt = []
            for logp, text, node, ys, done in beams:
                if done:
                    nxt.append((logp, text, node, ys, True))
                    continue
                legal, terminal = self._legal(field, text, node)
                if not legal and not terminal:
                    continue
                logits = self.model.decode_step(
                    mem, sm, torch.tensor([ys], device=self.device))
                logprobs = torch.log_softmax(logits[0], dim=-1)
                if terminal:
                    nxt.append((logp + float(logprobs[EOS]), text, node, ys, True))
                for ch in legal:
                    ci = v.get(ch)
                    if ci is None:
                        continue
                    nxt.append((logp + float(logprobs[ci]), text + ch,
                                self._advance(field, node, ch), ys + [ci], False))
            if not nxt:
                break
            beams = sorted(nxt, key=lambda b: b[0] / max(len(b[1]), 1), reverse=True)[:width]
            if all(b[4] for b in beams):
                break
        finished = [b for b in beams if b[4]]
        if not finished:
            return None, -99.0
        best = max(finished, key=lambda b: b[0] / max(len(b[1]) + 1, 1))
        return best[1], best[0] / max(len(best[1]) + 1, 1)


def load(model_dir, device):
    vocab = json.loads((Path(model_dir) / "vocab.json").read_text())["itos"]
    model = Transducer(len(vocab)).to(device)
    model.load_state_dict(torch.load(Path(model_dir) / "transducer.pt",
                                     map_location=device))
    model.eval()
    return model, vocab


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="/tmp/mib-transducer")
    ap.add_argument("--pairs", default="/tmp/mib-pairs/real_pairs.jsonl")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model, vocab = load(args.model, device)
    tb = TrieBeam(model, vocab, device)

    from rapidfuzz import fuzz, process
    JOINT = [f"{a} {b}" for a in NAMES["first"] for b in NAMES["last"]]

    def baseline(field, src):
        from mib.parse_ocr import _snap_value
        from mib.pipeline import _snap_name
        if field == "applicant_name":
            v0, _ = _snap_value(field, src)
            q = v0 if v0 else src.strip()
            hit = process.extractOne(q, JOINT, scorer=fuzz.ratio, score_cutoff=55)
            return hit[0] if hit else _snap_name(q)
        v0, _ = _snap_value(field, src)
        return v0 if v0 is not None else src.strip()

    pairs = [json.loads(l) for l in open(args.pairs)]
    pairs = [p for p in pairs if is_test(p["case"]) and p["field"] in tb.tries
             and p["src"].strip() != p["tgt"]]
    if args.limit:
        pairs = pairs[:args.limit]

    print(f"{len(pairs)} garbled real test pairs")
    print(f"{'field':18} {'n':>4} {'baseline':>9} {'transducer':>11} {'gated':>7}")
    for field in sorted({p["field"] for p in pairs}):
        fp = [p for p in pairs if p["field"] == field]
        base_ok = trans_ok = gated_ok = 0
        for p in fp:
            b = baseline(field, p["src"])
            t, score = tb.decode(field, p["src"])
            g = t if (t is not None and score > -1.2) else b
            base_ok += b == p["tgt"]
            trans_ok += t == p["tgt"]
            gated_ok += g == p["tgt"]
        print(f"{field:18} {len(fp):4} {base_ok/len(fp):9.1%} "
              f"{trans_ok/len(fp):11.1%} {gated_ok/len(fp):7.1%}")


if __name__ == "__main__":
    main()
