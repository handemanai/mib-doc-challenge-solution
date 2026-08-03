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
| `models/en_PP-OCRv5_rec_mobile.onnx` (7.9 MB; SHA-256 `c3461add59bb4323ecba96a492ab75e06dda42467c9e3d0c18db5d1d21924be8`) | PP-OCRv5 English mobile text-recognition model | [PaddleOCR / PaddlePaddle](https://github.com/PaddlePaddle/PaddleOCR), distributed in a [versioned RapidAI ONNX artifact](https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.0/onnx/PP-OCRv5/rec/en_PP-OCRv5_rec_mobile.onnx) | Apache-2.0 |

The ONNX file is committed unchanged from the obtained model artifact and is
the only third-party *artifact* committed to this repository. Its PaddlePaddle
origin is independently inspectable in the file: the graph name is
`PaddlePaddle Graph in PIR mode`, and its `character` metadata contains the
upstream English character dictionary.

The Apache-2.0 text that covers this model, RapidOCR, and FlatBuffers is kept at
`THIRD_PARTY_LICENSES/Apache-2.0.txt`. The Docker build copies the third-party
license texts, this notice, and the repository MIT license to
`/usr/share/doc/mib-solution/`.

The final image also contains the three ONNX models bundled with RapidOCR. An
inventory of application and bundled RapidOCR model artifacts counts 28,750,436
bytes in total; the largest is RapidOCR's bundled
`ch_PP-OCRv4_rec_infer.onnx` at 10,857,958 bytes. That recognizer is present as
package data but is not selected by this runtime. Both figures remain far below
the challenge's 1 GiB total and 250 MiB per-artifact limits.

## Runtime dependencies (installed at image build; not vendored here)

Python package versions are pinned exactly in `Dockerfile`. Wheel files are not
hash-locked, and the Debian libraries are resolved at build time from the
repositories configured by the digest-pinned base image. The accepted release
therefore binds the built image as well as the source checkout.

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

`rapidocr-onnxruntime` bundles its own detection, classification, and recognition
ONNX models
(`ch_PP-OCRv4_det`, `ch_PP-OCRv4_rec`, `ch_ppocr_mobile_v2.0_cls`), also
PaddleOCR-derived and Apache-2.0. The bundled detector and classifier are used;
the recognizer above replaces the bundled `rec` model.

Python packaging tools (`pip`, `setuptools`, and `wheel`) come from the pinned
base image rather than `requirements.txt`; their versions are therefore fixed
by the base digest. The installed wheels retain their own license files and
third-party notices under `/usr/local/lib/python3.11/site-packages/` in the
built image.

The base is the multi-architecture image index
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

These artifacts were produced for this solution; none is keyed to a case ID or
contains a case-to-answer mapping. The public MIB Doc Challenge training packets
and labels are Copyright (c) 2026 8090, Inc. and MIT-licensed in the challenge
repository; its copyright notice and license text are retained at
`THIRD_PARTY_LICENSES/MIB-Challenge-MIT.txt`. The coefficients, vocabulary, and
pixel templates below were derived from that public data and synthetic
perturbations. `pix_bank.npz` contains transformed visible line crops, not
validation data or case-keyed answers.

| File | What it is | Derived from |
| --- | --- | --- |
| `calibrator.json` | Logistic + isotonic confidence calibrator coefficients | out-of-fold fit on dev evidence features |
| `path_confidence.json` | Per-decision-path empirical accuracy priors (84 paths) | dev decision paths |
| `reason_buckets.json` | Per-reason-bucket accuracy shrink targets (23 buckets) | dev decision reasons |
| `name_vocab.json` | Applicant-name syllable lexicon (first/last token sets) | train label strings |
| `pix_bank.npz` | Empirical pixel-template bank for the closed-vocabulary decoder | real line crops from the harvest half of dev |
| `confusion_costs.json` | Character-level edit costs (ins/del/sub) | OCR confusion pairs mined from our own output |
| `transducer_enc.int8.onnx`, `transducer_dec.int8.onnx`, `transducer_vocab.json` | OCR-correction transducer, trained from scratch by us; **ships disabled** (`MIB_TRANSDUCER=0`) | mined + synthetic confusion pairs |

### `pix_bank.npz` key scope

The bank is keyed `v|{label}|{value}|{i}`: a crop of the pixels that spell
`{value}` under field label `{label}`. It contains templates for exactly the ten
field labels queried by the decoder. No archive key contains a case ID, and the
archive has no `Case ID` field entries. The runtime obtains `case_id` from the
PDF filename stem rather than from a pixel match.

See `MEMO.md` for the decoder's actual role.
