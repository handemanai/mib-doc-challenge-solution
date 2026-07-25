#!/usr/bin/env python3
"""Train the MIB char-level OCR-correction transducer.

From-scratch encoder-decoder Transformer (~4M params — a task model, not a
language model: it cannot follow instructions, so it reinstalls no injection
surface). One model serves all fields via a source-side field tag. The loss is
edit-weighted cross-entropy: target positions produced by an edit (difflib
opcodes vs the source) weigh EDIT_W, copies weigh 1 — plain CE teaches a
copier (the X-post's key trick, reproduced here).

Training data: real mined pairs (dev packets only; test cases held out by the
same hash as bench_correctors) + synthetic degrade-render pairs from the real
OCR engine. Holdout packets contribute nothing.

    venv-train python tools/transducer/train.py --epochs 12 \
        --real /tmp/mib-pairs/real_pairs.jsonl --synth /tmp/mib-pairs/synth.jsonl
"""
import argparse
import difflib
import hashlib
import json
import math
import random
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

FIELD_TAGS = ["applicant_name", "species_code", "home_world", "visa_class",
              "sponsor_id", "arrival_date", "declared_purpose", "risk_flags"]
PAD, BOS, EOS, UNK = 0, 1, 2, 3
MAX_SRC, MAX_TGT = 56, 44
EDIT_W = 4.0


def is_test(case_id):
    return int(hashlib.md5(case_id.encode()).hexdigest(), 16) % 5 == 1


def load_pairs(real_path, synth_path):
    train, test = [], []
    for line in open(real_path):
        p = json.loads(line)
        if p["field"] not in FIELD_TAGS or p["field"] == "risk_flags":
            continue
        if len(p["src"]) < 2 or len(p["src"]) > MAX_SRC - 8 or len(p["tgt"]) > MAX_TGT - 4:
            continue
        (test if is_test(p["case"]) else train).append(p)
    for line in open(synth_path):
        p = json.loads(line)
        if len(p["src"]) < 2 or len(p["src"]) > MAX_SRC - 8 or len(p["tgt"]) > MAX_TGT - 4:
            continue
        train.append(p)
    return train, test


class Vocab:
    def __init__(self, pairs):
        chars = sorted({c for p in pairs for c in p["src"] + p["tgt"]})
        self.itos = ["<pad>", "<bos>", "<eos>", "<unk>"] + \
                    [f"<{f}>" for f in FIELD_TAGS] + chars
        self.stoi = {s: i for i, s in enumerate(self.itos)}

    def tag(self, field):
        return self.stoi[f"<{field}>"]

    def enc(self, s):
        return [self.stoi.get(c, UNK) for c in s]

    def __len__(self):
        return len(self.itos)


def edit_weights(src, tgt):
    """Per-target-char loss weights from difflib opcodes: edits >> copies."""
    w = [1.0] * len(tgt)
    for op, _, _, j1, j2 in difflib.SequenceMatcher(None, src, tgt).get_opcodes():
        if op in ("replace", "insert"):
            for j in range(j1, min(j2, len(tgt))):
                w[j] = EDIT_W
    return w


def make_batch(pairs, vocab, device):
    B = len(pairs)
    src = torch.full((B, MAX_SRC), PAD, dtype=torch.long)
    tgt_in = torch.full((B, MAX_TGT), PAD, dtype=torch.long)
    tgt_out = torch.full((B, MAX_TGT), PAD, dtype=torch.long)
    w = torch.zeros((B, MAX_TGT))
    for i, p in enumerate(pairs):
        s = [vocab.tag(p["field"])] + vocab.enc(p["src"])[: MAX_SRC - 1]
        t = vocab.enc(p["tgt"])[: MAX_TGT - 2]
        src[i, :len(s)] = torch.tensor(s)
        ti = [BOS] + t
        to = t + [EOS]
        tgt_in[i, :len(ti)] = torch.tensor(ti)
        tgt_out[i, :len(to)] = torch.tensor(to)
        ew = edit_weights(p["src"], p["tgt"])[: MAX_TGT - 2] + [1.0]
        w[i, :len(to)] = torch.tensor(ew[:len(to)])
    return (x.to(device) for x in (src, tgt_in, tgt_out, w))


class Transducer(nn.Module):
    def __init__(self, vocab_size, d=192, heads=4, layers=3, ffn=512):
        super().__init__()
        self.d = d
        self.emb = nn.Embedding(vocab_size, d, padding_idx=PAD)
        self.pos = nn.Parameter(torch.zeros(1, max(MAX_SRC, MAX_TGT), d))
        self.tr = nn.Transformer(
            d_model=d, nhead=heads, num_encoder_layers=layers,
            num_decoder_layers=layers, dim_feedforward=ffn, dropout=0.1,
            batch_first=True)
        self.tr.encoder.enable_nested_tensor = False  # op missing on MPS
        self.tr.encoder.use_nested_tensor = False
        self.out = nn.Linear(d, vocab_size)

    def forward(self, src, tgt_in):
        sm = src == PAD
        tm = tgt_in == PAD
        causal = nn.Transformer.generate_square_subsequent_mask(tgt_in.size(1), device=src.device)
        h = self.tr(self.emb(src) + self.pos[:, :src.size(1)],
                    self.emb(tgt_in) + self.pos[:, :tgt_in.size(1)],
                    src_key_padding_mask=sm, tgt_key_padding_mask=tm,
                    memory_key_padding_mask=sm, tgt_mask=causal)
        return self.out(h)

    def encode(self, src):
        sm = src == PAD
        mem = self.tr.encoder(self.emb(src) + self.pos[:, :src.size(1)],
                              src_key_padding_mask=sm)
        return mem, sm

    def decode_step(self, mem, sm, tgt_in):
        causal = nn.Transformer.generate_square_subsequent_mask(tgt_in.size(1), device=tgt_in.device)
        h = self.tr.decoder(self.emb(tgt_in) + self.pos[:, :tgt_in.size(1)], mem,
                            tgt_mask=causal, memory_key_padding_mask=sm)
        return self.out(h[:, -1])


def greedy(model, vocab, field, src_text, device):
    src = torch.full((1, MAX_SRC), PAD, dtype=torch.long, device=device)
    s = [vocab.tag(field)] + vocab.enc(src_text)[: MAX_SRC - 1]
    src[0, :len(s)] = torch.tensor(s, device=device)
    mem, sm = model.encode(src)
    ys = torch.tensor([[BOS]], device=device)
    out = []
    for _ in range(MAX_TGT - 1):
        logits = model.decode_step(mem, sm, ys)
        nxt = int(logits.argmax(-1))
        if nxt == EOS:
            break
        out.append(nxt)
        ys = torch.cat([ys, torch.tensor([[nxt]], device=device)], dim=1)
    return "".join(vocab.itos[i] if i >= 4 + len(FIELD_TAGS) else "" for i in out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", default="/tmp/mib-pairs/real_pairs.jsonl")
    ap.add_argument("--synth", default="/tmp/mib-pairs/synth.jsonl")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="/tmp/mib-transducer")
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    device = "mps" if torch.backends.mps.is_available() else "cpu"

    train, test = load_pairs(args.real, args.synth)
    vocab = Vocab(train + test)
    model = Transducer(len(vocab)).to(device)
    n_par = sum(p.numel() for p in model.parameters())
    print(f"train {len(train)} pairs, test {len(test)}, vocab {len(vocab)}, "
          f"params {n_par/1e6:.1f}M, device {device}")

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)

    for ep in range(args.epochs):
        model.train()
        random.shuffle(train)
        tot = nb = 0
        for i in range(0, len(train), args.batch):
            src, tgt_in, tgt_out, w = make_batch(train[i:i + args.batch], vocab, device)
            logits = model(src, tgt_in)
            ce = nn.functional.cross_entropy(
                logits.reshape(-1, logits.size(-1)), tgt_out.reshape(-1),
                reduction="none").reshape(tgt_out.shape)
            loss = (ce * w).sum() / w.sum()
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tot += float(loss)
            nb += 1
        sched.step()

        # quick val on real garbled test pairs (greedy, unconstrained)
        model.eval()
        with torch.no_grad():
            garbled = [p for p in test if p["src"].strip() != p["tgt"]][:400]
            clean = [p for p in test if p["src"].strip() == p["tgt"]][:200]
            fix = sum(greedy(model, vocab, p["field"], p["src"], device) == p["tgt"]
                      for p in garbled)
            keep = sum(greedy(model, vocab, p["field"], p["src"], device) == p["tgt"]
                       for p in clean)
        print(f"ep {ep}: loss {tot/max(nb,1):.4f}  val-fix {fix}/{len(garbled)} "
              f"({fix/max(len(garbled),1):.1%})  val-keep {keep}/{len(clean)}", flush=True)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out / "transducer.pt")
    (out / "vocab.json").write_text(json.dumps({"itos": vocab.itos}))
    print(f"saved -> {out}")


if __name__ == "__main__":
    main()
