# Reviewer guide — public verification map

This guide links only evidence committed to this public repository. The dated
performance register is a historical research log and mentions private working
receipts that are not published; those absent receipts are not offered as proof
of the final release.

## 1. Run the scoring contract

From the solution checkout, set `CHALLENGE_DIR` to an absolute checkout of the
official challenge repository:

```bash
CHALLENGE_DIR=/absolute/path/to/mib-doc-challenge
OUTPUT_DIR=/tmp/mib-review-output
PRODUCER_SHA=4313d28b34abc4cef4c89586060f4d3d34848c88
mkdir -p "$OUTPUT_DIR"
git checkout --detach "$PRODUCER_SHA"

docker build --platform linux/amd64 \
  --label "org.opencontainers.image.revision=$PRODUCER_SHA" \
  -t "mib-review:$PRODUCER_SHA" .
docker run --rm --platform linux/amd64 \
  --network none --cpus 4 --memory 8g --pids-limit 512 \
  --read-only --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,size=2g \
  --mount type=bind,src="$CHALLENGE_DIR/data/validation",dst=/input,readonly \
  --mount type=bind,src="$OUTPUT_DIR",dst=/output \
  "mib-review:$PRODUCER_SHA" /input /output/predictions.jsonl

python3 "$CHALLENGE_DIR/scripts/validate_submission.py" \
  --submission "$OUTPUT_DIR/predictions.jsonl" \
  --manifest "$CHALLENGE_DIR/data/validation_manifest.csv" \
  --require-complete
```

The scoring image copies the runtime source/model directories and entry scripts;
license and notice files are also included. Audit and fitting tools are not part
of the inference image. The model and dependency inventory is documented in the
source-bound
[`NOTICE.md`](https://github.com/handemanai/mib-doc-challenge-solution/blob/4313d28b34abc4cef4c89586060f4d3d34848c88/NOTICE.md).

## 2. Trace one decision

Append `--ledger /output/evidence.jsonl` to the container command. Each ledger
row records final fields, selected evidence source, rank, snap score and
agreement, decision path, rank-1 payloads and conflicts, view metadata, fusion
details, and extraction attempts.

The decision route is directly inspectable:

- [`mib/pipeline.py`](../mib/pipeline.py) extracts candidates, applies evidence
  gates and rank-1 authority, calls deterministic adjudication, and computes
  confidence afterward.
- [`mib/rules.py`](../mib/rules.py) contains the field policy. Its
  `optimal_decision` helper is an offline scoring-matrix utility and is not
  called by the production path.
- [`mib/two_ledger.py`](../mib/two_ledger.py) selects native fields, permits only
  defined adverse decision transitions, and applies final consistency.

Ordinary approvals whose emitted fields contradict policy narrow to
`NEEDS_REVIEW`. A visible rank-1 adjudicator finding on an accepted note surface
may override lower-rank fields. Native-text authority additionally requires an
exact 250-DPI composited raster/OCR reread; a mismatch strips authority. Pages
confidently naming a foreign case are quarantined; native-only alternate
authority additionally requires an exact body Case ID. Conflicts remain
recorded, and emitted fields change only when explicit correction text is
present.

## 3. Inspect hostile-document handling

The runtime has no LLM or VLM and invokes no barcode or QR-decoding path. That
makes prompt following unavailable, but it does not eliminate evidence
poisoning. The relevant protections are:

- [`mib/forensics.py`](../mib/forensics.py): span visibility, draw-order, hidden
  optional-content, and container signals;
- [`mib/caseid.py`](../mib/caseid.py): packet identity resolution;
- [`mib/extract.py`](../mib/extract.py): foreign body-case detection used by
  the pipeline's page rejection gate;
- [`mib/pipeline.py`](../mib/pipeline.py): hidden-span masking before image
  enhancement and authority-aware evidence selection;
- [`tests/test_visible_span_security.py`](../tests/test_visible_span_security.py)
  and [`tests/test_native_text_rank1_corroboration.py`](../tests/test_native_text_rank1_corroboration.py):
  viewer-binding and authority corroboration regressions;
- [`tests/redteam_corpus/`](../tests/redteam_corpus/): twelve tracked clean and
  hostile PDFs;
- [`tests/test_redteam.py`](../tests/test_redteam.py): clean-twin field and
  adjudication checks plus hidden-token leak checks;
- [`tests/test_untrusted_container_guard.py`](../tests/test_untrusted_container_guard.py)
  and [`tests/test_note_authority_adversarial.py`](../tests/test_note_authority_adversarial.py):
  untrusted text-layer and forged-note controls.

The runtime does not parse hidden verdict direction. Generic hidden-content
presence and field-category indicators may remain as audit, conservative
distrust, or calibration signals; hidden values never populate fields or support
`APPROVED` or `DENIED`. The red-team
claim is scoped accordingly: hostile twins preserve emitted fields and
adjudication, except the intentionally evidence-withheld case, rather than a
blanket byte-identity claim about every ledger or confidence field.

## 4. Inspect safety boundaries

- [`mib/flagread.py`](../mib/flagread.py),
  [`mib/worldread.py`](../mib/worldread.py), and
  [`mib/sponsorread.py`](../mib/sponsorread.py) emit only adverse evidence.
- [`mib/feeread.py`](../mib/feeread.py) requires positive visual evidence before
  an approval-adjacent `paid` read.
- [`mib/forensics.py`](../mib/forensics.py) binds cancellation words and strokes
  to the viewer; [`mib/parse_ocr.py`](../mib/parse_ocr.py) rejects negated
  authority and retains each accepted raw spelling beside its canonical value;
  [`mib/pipeline.py`](../mib/pipeline.py) resolves matching strike aliases,
  prevents ambiguous adverse cancellation from creating approval, and rebuilds
  rank-1 values, evidence, and conflicts together for binder-consistent
  sanitization. The provenance is deliberately conservative at token/field
  scope; it does not claim exact occurrence or page attribution.
- [`mib/noteread.py`](../mib/noteread.py) recovers only deny/review directions by
  default; approval recovery remains disabled.
- [`tests/test_final_consistency.py`](../tests/test_final_consistency.py) covers
  both ordinary contradiction demotion and the rank-1 exception.
- [`tests/test_native_sanitization.py`](../tests/test_native_sanitization.py) and
  [`tests/test_two_ledger_gates.py`](../tests/test_two_ledger_gates.py) cover
  native-field validity and monotone fusion.
- [`tests/test_wave5.py`](../tests/test_wave5.py) covers negation and raw-alias
  strike regressions; [`tests/test_native_artifact_binding.py`](../tests/test_native_artifact_binding.py)
  covers direct embedded-scan revalidation and binder-consistent rank-1
  sanitization.

The one development false approval is documented in
[`experiments/CFA-MIB-000865-visible-forensic.md`](../experiments/CFA-MIB-000865-visible-forensic.md).
That document establishes absence across the channels actually audited; it does
not claim metaphysical irreducibility or private-set validation.

## 5. Inspect completion and runtime controls

- [`scripts/run_shard.py`](../scripts/run_shard.py) applies per-case deadlines,
  flushes and `fsync`s every state, and actively requests worker replacement
  after 48 cases by default.
- [`scripts/predict.py`](../scripts/predict.py) implements the heartbeat
  watchdog, unfinished-tail resume, retry budget, completeness fallback, atomic
  prediction refresh, and batch governor. Up to 128 failed-case candidates may
  receive one fresh-process retry, subject to the measured 3,600-second retry
  wall and the hard batch-finalization reserve.
- [`tests/test_watchdog.py`](../tests/test_watchdog.py) covers worker death,
  lower-level hangs, and one-case recycling identity.
- [`tests/test_governor.py`](../tests/test_governor.py) covers governor
  transitions and level-0 equivalence.
- [`tests/test_merge_case_retries.py`](../tests/test_merge_case_retries.py)
  covers retry selection and merge behavior.
- [`tests/test_batch_deadline.py`](../tests/test_batch_deadline.py) covers the
  hard finalization reserve, bounded worker reap, durable-state preservation,
  and conservative unresolved-case backfill.

Governor level 0 is tested as output-equivalent to the ungoverned path. The
12-case red-team output repeated byte-identically across two native ARM64 runs
and one emulated AMD64 run. A changing governor schedule or deep
timeout-boundary stress may send different cases through reduced OCR work, so
full-batch cross-schedule byte identity is not claimed.

## 6. Inspect test coverage

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt pytest
MIB_CHALLENGE_DIR="$CHALLENGE_DIR" .venv/bin/python -m pytest tests/ -q
```

Data-backed tests need the challenge checkout, and provenance tests need Git.
When those prerequisites are absent, the harness emits controlled skips. The
test result should therefore be reported with its environment and skip count,
not as a context-free pass number.

With the full challenge checkout mounted, an executable 2-GiB test tmpfs, and
the pinned release image dependencies, the final source reported **1,183
passed, 106 controlled skips, and zero failures**. The 12-case red-team output
was byte-identical across two native ARM64 runs and one emulated AMD64 run. On
the eight-case OCR-sensitive panel, adjudications matched across architectures,
while emitted fields were not row-identical on any of the eight. Exactly two
AMD64 cases reached both the per-case timeout and retry-failure path and emitted
conservative fallback rows. The ARM64 fee-reader panel was unchanged from the
prior producer.

## 7. Final identity check

The release documents record the exact source, prediction, and run-result
identities. This check must print no matches:

```bash
rg -n 'FINAL_(RUNTIME_SOURCE_SHA|PREDICTIONS_SHA256|VALIDATION_[A-Z0-9_]+)' \
  README.md SUBMISSION.md MEMO.md
```

The local Docker image IDs are ARM64
`sha256:21515e59b31fecaed2eb9983527c0751079abc9c9d3c7711142214c523bdae3f`
(286,493,358 bytes) and AMD64
`sha256:f6447a9720c0ca52616d83f245ecb804d418b94bd503f8fe57fe551a3e36f95d`
(316,434,546 bytes). Full source/runtime manifest binding passed for the native
ARM64 release path. Direct embedded-scan reads are independently covered by the
viewer-binding and strict artifact-binder regressions above.

The public proof surface is therefore: source, tests, committed adversarial
corpus, the visible-evidence forensic, dependency/model provenance, the final
public Git commit, and the submitted prediction hash. Private review kits,
cached states, and unpublished receipts are not public verification. Historical
development measurements lacking tracked artifacts should be read as internal
results, not independently reproducible evidence.
