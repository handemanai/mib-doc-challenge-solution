# Third-Party Notices and Artifact Provenance

This file records every application runtime dependency in the scoring image and
states the origin of each file under `models/`. It exists so a reviewer can tell
at a glance which bytes are ours, which are someone else's, and under what
terms. Base-image tooling and operating-system libraries are identified
separately below.

Our own source code is MIT-licensed (see `LICENSE`). That applies to the code in
this repository, not to the third-party components listed below.

## Redistributed third-party artifact

| File | Component | Upstream | License |
| --- | --- | --- | --- |
| `models/en_PP-OCRv5_rec_mobile.onnx` (7.9 MB; SHA-256 `c3461add59bb4323ecba96a492ab75e06dda42467c9e3d0c18db5d1d21924be8`) | PP-OCRv5 English mobile text-recognition model | [PaddleOCR / PaddlePaddle](https://github.com/PaddlePaddle/PaddleOCR), distributed as ONNX | Apache-2.0 |

The ONNX file is committed unchanged from the obtained model artifact and is
the only third-party *artifact* committed to this repository. Its PaddlePaddle
origin is independently inspectable in the file: the graph name is
`PaddlePaddle Graph in PIR mode`, and its `character` metadata contains the
upstream English character dictionary.

The Apache-2.0 text that covers this model, RapidOCR, and FlatBuffers is kept at
`THIRD_PARTY_LICENSES/Apache-2.0.txt`. The Docker build copies the third-party
license texts, this notice, and the repository MIT license to
`/usr/share/doc/mib-solution/`.

## Runtime dependencies (installed at image build; not vendored here)

Pinned in `Dockerfile`. Versions are exact because the score must reproduce from
a clean checkout.

| Package | Version | License |
| --- | --- | --- |
| PyMuPDF | 1.28.0 | AGPL-3.0-only or Artifex commercial license |
| rapidocr-onnxruntime | 1.4.4 | Apache-2.0 |
| onnxruntime | 1.20.1 | MIT |
| RapidFuzz | 3.14.5 | MIT |
| NumPy | 2.2.6 | BSD-3-Clause; bundled-component notices are included in the wheel |
| opencv-python | 4.11.0.86 | Apache-2.0; bundled third-party notices are included in the wheel |
| Pillow | 12.3.0 | MIT-CMU |
| PyYAML | 6.0.3 | MIT |
| Shapely | 2.1.2 | BSD-3-Clause; bundled GEOS is LGPL-2.1-or-later |
| coloredlogs | 15.0.1 | MIT |
| flatbuffers | 25.12.19 | Apache-2.0 |
| humanfriendly | 10.0 | MIT |
| mpmath | 1.3.0 | BSD-3-Clause |
| packaging | 26.2 | Apache-2.0 OR BSD-2-Clause |
| protobuf | 7.35.1 | BSD-3-Clause |
| pyclipper | 1.4.0 | MIT |
| six | 1.17.0 | MIT |
| sympy | 1.14.0 | BSD-3-Clause |
| tqdm | 4.70.0 | MPL-2.0 AND MIT |

`rapidocr-onnxruntime` bundles its own detection/classification ONNX models
(`ch_PP-OCRv4_det`, `ch_PP-OCRv4_rec`, `ch_ppocr_mobile_v2.0_cls`), also
PaddleOCR-derived and Apache-2.0. They are used for text detection; the
recognizer above replaces the bundled `rec` model.

Python packaging tools (`pip`, `setuptools`, and `wheel`) come from the pinned
base image rather than `requirements.txt`; their versions are therefore fixed
by the base digest. The installed wheels retain their own license files and
third-party notices under `/usr/local/lib/python3.11/site-packages/` in the
built image.

The base is the linux/amd64 image
`python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93`.
It also installs Debian's `libgl1`, `libglib2.0-0`, and `libgomp1`; their
copyright and license material remains available under `/usr/share/doc/` in the
built image.

### On PyMuPDF and AGPL-3.0

PyMuPDF is dual-licensed under AGPL-3.0-only or an Artifex commercial license.
This project relies on the AGPL option. The complete AGPL-3.0 text is kept at
`THIRD_PARTY_LICENSES/AGPL-3.0.txt`; the installed wheel's `COPYING` file states
the dual-license choice but does not itself reproduce the terms. Our own files
remain MIT-licensed; that does not change PyMuPDF's terms or the obligations
that apply when the combined image is conveyed.

## Artifacts we produced (`models/`)

None of these came from a third party, and none is keyed to a case ID or
contains an answer. All were derived from the public training data
(`data/train/` + `data/train_labels.csv`) that the challenge provides.

| File | What it is | Derived from |
| --- | --- | --- |
| `calibrator.json` | Logistic + isotonic confidence calibrator coefficients | out-of-fold fit on dev evidence features |
| `path_confidence.json` | Per-decision-path empirical accuracy priors (84 paths) | dev decision paths |
| `reason_buckets.json` | Per-reason-bucket accuracy shrink targets (23 buckets) | dev decision reasons |
| `name_vocab.json` | Applicant-name syllable lexicon (first/last token sets) | train label strings |
| `pix_bank.npz` | Empirical pixel-template bank for the closed-vocabulary decoder | real line crops from the harvest half of dev |
| `confusion_costs.json` | Character-level edit costs (ins/del/sub) | OCR confusion pairs mined from our own output |
| `transducer_enc.int8.onnx`, `transducer_dec.int8.onnx`, `transducer_vocab.json` | OCR-correction transducer, trained from scratch by us; **ships disabled** (`MIB_TRANSDUCER=0`) | mined + synthetic confusion pairs |

### A note on `pix_bank.npz` keys

The bank is keyed `v|{label}|{value}|{i}` — a crop of the pixels that spell
`{value}` under field label `{label}`. No key contains a case ID, and the
artifact holds templates for exactly the ten field labels the decoder queries.

This is worth stating explicitly because it was not always true. Because
`tools/pixharvest.py` harvests every field label it can verify, earlier revisions
also banked crops for the `Case ID:` field, whose *value* is a case ID string —
228 entries covering 177 training case IDs. They were harvest byproduct and
unreachable at run time (no code path queries the `Case ID:` label, and
`case_id` is taken from the PDF filename stem, never from a pixel match), but a
shipped artifact that greps as a per-PDF table is not worth defending, so they
were removed. Dropping them is output-neutral, verified by byte-identical
extraction states over a 20-case sample including the five slowest packets in
the validation set.

See `MEMO.md` for the decoder's actual role.
