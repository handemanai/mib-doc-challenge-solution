#!/usr/bin/env python3
"""Export the trained transducer to two int8 ONNX graphs (encoder + one
decoder step) so the runtime decodes with onnxruntime + numpy only — no torch
in the image. Verifies torch-vs-ONNX parity on sample decodes before writing.

    venv-train python tools/transducer/export_onnx.py --model /tmp/mib-transducer \
        --out models/
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train import MAX_SRC, MAX_TGT, PAD, Transducer  # noqa: E402


class EncoderWrap(torch.nn.Module):
    def __init__(self, m):
        super().__init__()
        self.m = m

    def forward(self, src):
        mem, sm = self.m.encode(src)
        return mem, sm


class StepWrap(torch.nn.Module):
    """Fixed-shape decoder step: ys is always (1, MAX_TGT) padded, t selects
    the output position. The causal mask stops position t from seeing the pad
    tail, so fixed shapes are exact — and export-safe (TorchScript bakes
    trace-time sequence lengths into attention reshapes otherwise)."""

    def __init__(self, m):
        super().__init__()
        self.m = m
        self.register_buffer(
            "causal", torch.nn.Transformer.generate_square_subsequent_mask(MAX_TGT))

    def forward(self, mem, sm, ys, t):
        h = self.m.tr.decoder(
            self.m.emb(ys) + self.m.pos[:, :MAX_TGT], mem,
            tgt_mask=self.causal, memory_key_padding_mask=sm)
        return self.m.out(h[:, t])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="/tmp/mib-transducer")
    ap.add_argument("--out", default="/tmp/mib-transducer")
    args = ap.parse_args()

    vocab = json.loads((Path(args.model) / "vocab.json").read_text())["itos"]
    model = Transducer(len(vocab))
    model.load_state_dict(torch.load(Path(args.model) / "transducer.pt",
                                     map_location="cpu"))
    model.eval()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    src = torch.randint(4, len(vocab), (1, MAX_SRC))
    src[0, 30:] = PAD
    with torch.no_grad():
        mem, sm = model.encode(src)

    torch.onnx.export(EncoderWrap(model), (src,), out / "transducer_enc.onnx",
                      input_names=["src"], output_names=["mem", "sm"],
                      dynamo=False, opset_version=17)
    ys = torch.full((1, MAX_TGT), PAD, dtype=torch.long)
    ys[0, :3] = torch.tensor([1, 5, 6])
    t = torch.tensor(2, dtype=torch.long)
    torch.onnx.export(StepWrap(model), (mem, sm, ys, t), out / "transducer_dec.onnx",
                      input_names=["mem", "sm", "ys", "t"], output_names=["logits"],
                      dynamo=False, opset_version=17)

    # int8 dynamic quantization
    from onnxruntime.quantization import QuantType, quantize_dynamic
    for stem in ("transducer_enc", "transducer_dec"):
        quantize_dynamic(str(out / f"{stem}.onnx"), str(out / f"{stem}.int8.onnx"),
                         weight_type=QuantType.QInt8)

    (out / "transducer_vocab.json").write_text(json.dumps({"itos": vocab}))

    # parity check: torch vs int8-ONNX greedy decode on a few sources
    import onnxruntime as ort
    enc = ort.InferenceSession(str(out / "transducer_enc.int8.onnx"))
    dec = ort.InferenceSession(str(out / "transducer_dec.int8.onnx"))
    stoi = {s: i for i, s in enumerate(vocab)}

    def torch_greedy(field, text):
        s = [stoi[f"<{field}>"]] + [stoi.get(c, 3) for c in text][: MAX_SRC - 1]
        x = torch.full((1, MAX_SRC), PAD, dtype=torch.long)
        x[0, :len(s)] = torch.tensor(s)
        with torch.no_grad():
            m, pm = model.encode(x)
            ys = [1]
            for _ in range(MAX_TGT - 1):
                lg = model.decode_step(m, pm, torch.tensor([ys]))
                nxt = int(lg.argmax(-1))
                if nxt == 2:
                    break
                ys.append(nxt)
        return ys[1:]

    def onnx_greedy(field, text):
        s = [stoi[f"<{field}>"]] + [stoi.get(c, 3) for c in text][: MAX_SRC - 1]
        x = np.full((1, MAX_SRC), PAD, dtype=np.int64)
        x[0, :len(s)] = s
        m, pm = enc.run(None, {"src": x})
        ys = [1]
        for _ in range(MAX_TGT - 1):
            yf = np.full((1, MAX_TGT), PAD, dtype=np.int64)
            yf[0, :len(ys)] = ys
            lg = dec.run(None, {"mem": m, "sm": pm, "ys": yf,
                                "t": np.array(len(ys) - 1, dtype=np.int64)})[0]
            nxt = int(lg[0].argmax())
            if nxt == 2:
                break
            ys.append(nxt)
        return ys[1:]

    samples = [("applicant_name", "Zaul lxonax"), ("declared_purpose", "reactar mainenance"),
               ("home_world", "Mas Dome-7"), ("visa_class", "XW-l")]
    agree = sum(torch_greedy(f, t) == onnx_greedy(f, t) for f, t in samples)
    sizes = {p.name: p.stat().st_size // 1024 for p in out.glob("transducer_*.int8.onnx")}
    print(f"parity {agree}/{len(samples)}; int8 sizes (KB): {sizes}")


if __name__ == "__main__":
    main()
