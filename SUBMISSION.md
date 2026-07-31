# MIB Doc Challenge — Submission

- **Solution repository (public, contains `Dockerfile`):** <https://github.com/handemanai/mib-doc-challenge-solution>
- **Candidate:** handemanai

## What this is

An offline, CPU-only adjudication engine for the MIB intergalactic intake desk.
It reads adversarial PDF case packets, extracts the nine applicant fields, and
recommends `APPROVED` / `DENIED` / `NEEDS_REVIEW` with a calibrated confidence.
Every decision is backed by a per-case evidence ledger.

See `MEMO.md` for the full technical write-up (approach, negative results,
failure modes, and what another week buys).

## Runtime contract compliance

- Runs under `--network none --cpus 4 --memory 8g --read-only --tmpfs /tmp`.
- Entrypoint accepts `<input_pdf_dir> <output_predictions_path>`.
- No LLM, VLM, cloud OCR, or network service at inference time. OCR is RapidOCR
  (PP-OCRv4 mobile detector + en_PP-OCRv5 mobile recognizer, ONNX); everything
  else is classical CV, deterministic rules, and an optional candidate-trained
  2.6M-parameter character transducer that is disabled by default (see MEMO.md)
  and whose trie-constrained decoder cannot emit values outside the legal field
  vocabularies. Nothing in the runtime follows instructions, so the injection
  surface the dataset targets does not exist in this system.
- Measured under those exact flags via the organizers' own
  `scripts/run_docker_submission.py`: **0.27 GiB image** (4 GiB cap), **12 MB of
  model artifacts** (1 GiB total / 250 MiB per-artifact caps), **2.88 GiB peak
  RSS** (8 GiB cap), **3.41s/PDF** (6s budget) projecting to **4.7h** against the
  8h20m limit. Slowest packet in the corpus: 62.7s against the 120s per-case
  deadline.
- Deterministic seeds; two clean-checkout runs produce byte-identical output.
- Per-case deadlines, a parent heartbeat watchdog, and planned worker recycling
  keep a single packet or a native-library process-lifetime fault from
  preventing validator-safe output. Completed rows are durable before a worker
  is replaced, and the scorer-facing file is refreshed during long runs.

## Reproduce

Run from a checkout with the challenge repository's `data/` available alongside
(clone `github.com/8090-inc/mib-doc-challenge` for `data/validation`,
`data/validation_manifest.csv`, and `scripts/validate_submission.py`), and
create the output directory first: `mkdir -p /tmp/mib-out`.

```bash
docker build -t mib-submission .
docker run --rm --network none --cpus 4 --memory 8g --read-only \
  --tmpfs /tmp --mount type=bind,src="$PWD/data/validation",dst=/input,readonly \
  --mount type=bind,src=/tmp/mib-out,dst=/output \
  mib-submission /input /output/predictions.jsonl
python3 scripts/validate_submission.py \
  --submission /tmp/mib-out/predictions.jsonl \
  --manifest data/validation_manifest.csv
```

## Predictions

The submitted `predictions.jsonl` is not in this repository — it lives in the
challenge repository under `submissions/handemanai/`, together with the memo and
the provenance record that ties those 5,000 rows to a commit of this repository.
Reproducing the command above on `data/validation` regenerates it; it passes
`scripts/validate_submission.py` against `data/validation_manifest.csv` with
5,000 records and no missing cases.

## Documentation-only commits after `53dbe7a`

The submitted `predictions.jsonl` was generated at commit `53dbe7a` of this
repository. Every commit after `53dbe7a` touches documentation and experiment
receipts only — nothing under `mib/`, `scripts/`, `models/`, `tests/`,
`tools/`, `Dockerfile`, or `run.sh` changes, verifiable with
`git diff 53dbe7a..HEAD -- mib scripts models tests tools Dockerfile run.sh`
(empty output), so a rebuild at any later commit reproduces the same rows.
