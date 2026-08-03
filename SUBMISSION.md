# MIB Doc Challenge — Submission

- **Solution repository:** <https://github.com/handemanai/mib-doc-challenge-solution>
- **Candidate:** handemanai

## Summary

This is an offline, CPU-only adjudication engine. It extracts the nine required
fields from adversarial PDF packets and emits `APPROVED`, `DENIED`, or
`NEEDS_REVIEW` plus calibrated confidence. Decisions use deterministic evidence
and policy rules. Expected value is used only for offline evaluation of proposed
policy changes; confidence is computed after the decision.

The runtime contains no LLM, VLM, cloud OCR, network service, or component that
follows natural-language instructions. That removes prompt following as an
execution path, but it does not make hostile documents harmless. Hidden and
visible evidence poisoning are addressed with PDF forensics, hidden-span masking,
case/page binding, ranked evidence, source-specific authority, and conservative
review gates. The runtime does not parse hidden verdict direction. Generic
hidden-content presence may remain an audit, conservative distrust, or
calibration signal; hidden values never populate fields or support approval or
denial.

## Runtime contract

- Required interface: two positional arguments,
  `<input_pdf_dir> <output_predictions_path>`; optional audit flags are also
  available for reviewer runs.
- Linux/AMD64 reproduction flags: `--platform linux/amd64 --network none --cpus 4
  --memory 8g --pids-limit 512 --read-only --security-opt no-new-privileges
  --tmpfs /tmp:rw,nosuid,nodev,size=2g`.
- Runtime stack: RapidOCR/ONNX plus classical PDF, image, parsing, and policy
  code. The optional candidate-trained character transducer ships disabled.
- Final native-ARM64 generation run: `19,186.18` seconds,
  `3.8372` s/PDF, with 82 fresh-process retries, all recovered (81 watchdog exits
  with missing primary state and one primary per-case timeout), zero terminal
  failures, governor level 0 throughout, and no batch-deadline backfill; the 8 GiB hard memory limit is enforced
  by Docker.
- Release images: 316,434,546 bytes for AMD64 and 286,493,358 bytes for ARM64;
  28,750,436 bytes total model artifacts and 10,857,958 bytes largest artifact,
  including RapidOCR's bundled ONNX files.
- Each case has a deadline; a parent heartbeat handles lower-level hangs; active
  worker recycling replaces each worker after 48 cases; and the batch governor
  can reduce future OCR work if projected runtime approaches the hard limit.
- Up to 128 failed-case candidates may receive one fresh-process retry, but the
  retry phase remains bounded by a measured 3,600-second wall and the batch
  finalization reserve.
- The supervisor reserves finalization time, signals all workers before one
  bounded reap, preserves durable states, and atomically backfills any unresolved
  cases with validator-safe `NEEDS_REVIEW` rows.
- Governor level 0 is tested as output-equivalent to the ungoverned path. The
  12-case red-team output repeated byte-identically across two native ARM64 runs
  and one emulated AMD64 run; full-batch byte identity is not claimed across
  scheduling, governor, architecture, or timeout-boundary changes.
- With the full challenge checkout mounted, the pinned suite reported 1,183
  passed, 106 controlled skips, and zero failures.

## Reproduce and validate

Set `CHALLENGE_DIR` to an absolute checkout of the official challenge repository.
Run these commands from this solution repository:

```bash
CHALLENGE_DIR=/absolute/path/to/mib-doc-challenge
OUTPUT_DIR=/tmp/mib-submission-output
PRODUCER_SHA=4313d28b34abc4cef4c89586060f4d3d34848c88
mkdir -p "$OUTPUT_DIR"
git checkout --detach "$PRODUCER_SHA"

docker build --platform linux/amd64 \
  --label "org.opencontainers.image.revision=$PRODUCER_SHA" \
  -t "mib-submission:$PRODUCER_SHA" .
docker run --rm --platform linux/amd64 \
  --network none --cpus 4 --memory 8g --pids-limit 512 \
  --read-only --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,size=2g \
  --mount type=bind,src="$CHALLENGE_DIR/data/validation",dst=/input,readonly \
  --mount type=bind,src="$OUTPUT_DIR",dst=/output \
  "mib-submission:$PRODUCER_SHA" /input /output/predictions.jsonl

python3 "$CHALLENGE_DIR/scripts/validate_submission.py" \
  --submission "$OUTPUT_DIR/predictions.jsonl" \
  --manifest "$CHALLENGE_DIR/data/validation_manifest.csv" \
  --require-complete
```

The submitted prediction file lives in the challenge repository under
`submissions/handemanai/`; it is not duplicated here.

## Final release identity

These identities bind the public runtime source to the accepted prediction
artifact and are recorded together:

| Item | Final identity |
| --- | --- |
| Prediction-producing public source | `4313d28b34abc4cef4c89586060f4d3d34848c88` |
| ARM64 local Docker image ID | `sha256:21515e59b31fecaed2eb9983527c0751079abc9c9d3c7711142214c523bdae3f` (286,493,358 bytes) |
| AMD64 local Docker image ID | `sha256:f6447a9720c0ca52616d83f245ecb804d418b94bd503f8fe57fe551a3e36f95d` (316,434,546 bytes) |
| Predictions SHA-256 | `4ff616d449d1931b461220b21b9c9ca2d1dba3bb82b6e3c021bf659b8f2822be` |
| Submitted rows / missing rows | `5,000` / `0` |
| Output bytes | `1,683,486` |

The submitted predictions are generated end to end from the named public source;
no row is edited by hand. The generation run uses native ARM64. The linux/amd64
release image was built and tested under emulation on Apple silicon. On an
eight-case OCR-sensitive panel, adjudications matched across architectures,
while emitted fields were not row-identical on any of the eight. Exactly two
emulated AMD64 cases reached both the per-case timeout and retry-failure path
and emitted conservative fallback rows. The ARM64 fee-reader panel was
unchanged from the prior producer.
The full native-ARM64 source/runtime manifest binding passed. No full AMD64
throughput or cross-platform row-identity claim is made.

The baseline P0-B pixel observer uses an embedded scan only when resource,
geometry, crop/rotation, paint, and compositing checks bind it to the viewer's
page; otherwise it uses a new composited render. The independent native ledger
abstains when raw-scan authorization fails. Native-text rank-1 authority also
requires exact 250-DPI composited raster/OCR corroboration of every
authority-bearing value.

Viewer-trusted text and visible vector geometry are also required before a
manual cancellation can suppress evidence, and negated authority is rejected.
Accepted raw authority spellings remain bound to their canonical values so a
normalization alias cannot evade a matching strike. Sanitization rebuilds
rank-1 values, evidence, and conflicts together before the strict binder checks
the payload. Ambiguous adverse cancellation may narrow to review; it cannot
create approval. This is conservative token/field provenance, not exact
occurrence or page attribution.

## Authorship

I am a practicing surgeon, not a software engineer, and this is an experiment in
agentic coding rather than a job application. AI wrote nearly all of the code. I
set the goals, evidence standards, experiment boundaries, and promotion
decisions, including rejecting apparent score improvements that created unsafe
or poorly generalizing behaviour. I am stating that division honestly so the
work can be judged for what it is.

See `MEMO.md` for the technical argument and `docs/REVIEWER_GUIDE.md` for a map
of claims to public source and tests. The release
[`NOTICE.md`](NOTICE.md) records dependency licenses and model provenance; the
prediction-producing source identity is recorded separately above.
