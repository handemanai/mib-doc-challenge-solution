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
mkdir -p "$OUTPUT_DIR"

docker build --platform linux/amd64 -t mib-review .
docker run --rm --platform linux/amd64 \
  --network none --cpus 4 --memory 8g --pids-limit 512 \
  --read-only --tmpfs /tmp:size=2g \
  --mount type=bind,src="$CHALLENGE_DIR/data/validation",dst=/input,readonly \
  --mount type=bind,src="$OUTPUT_DIR",dst=/output \
  mib-review /input /output/predictions.jsonl

python3 "$CHALLENGE_DIR/scripts/validate_submission.py" \
  --submission "$OUTPUT_DIR/predictions.jsonl" \
  --manifest "$CHALLENGE_DIR/data/validation_manifest.csv" \
  --require-complete
```

The scoring image copies only `mib/`, the needed model artifacts,
`scripts/predict.py`, `scripts/run_shard.py`, and `run.sh`. Audit and fitting
tools are not part of the inference image. The model and dependency inventory is
in [`NOTICE.md`](../NOTICE.md).

## 2. Trace one decision

Append `--ledger /output/evidence.jsonl` to the container command. Each ledger
row shows the extracted fields, evidence rank and source, baseline/native fusion,
rank-1 payloads and conflicts, governor level, extraction attempts, and final
decision path.

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
`NEEDS_REVIEW`. The explicit exception is a signed, exactly case-bound rank-1
adjudicator finding, which has higher source authority under the field manual.
Such an approval can remain approved with its conflict recorded. A rank-1
finding may control adjudication, but emitted fields change only when the note
contains an explicit field correction.

## 3. Inspect hostile-document handling

The runtime has no LLM, VLM, barcode decoder, or other component that follows
natural-language instructions. That makes prompt following unavailable, but it
does not eliminate evidence poisoning. The relevant protections are:

- [`mib/forensics.py`](../mib/forensics.py): span visibility, draw-order, hidden
  optional-content, and container signals;
- [`mib/caseid.py`](../mib/caseid.py): packet identity resolution;
- [`mib/extract.py`](../mib/extract.py): foreign body-case detection used by
  the pipeline's page rejection gate;
- [`mib/pipeline.py`](../mib/pipeline.py): hidden-span masking before image
  enhancement and authority-aware evidence selection;
- [`tests/redteam_corpus/`](../tests/redteam_corpus/): twelve tracked clean and
  hostile PDFs;
- [`tests/test_redteam.py`](../tests/test_redteam.py): clean-twin field and
  adjudication checks plus hidden-token leak checks;
- [`tests/test_untrusted_container_guard.py`](../tests/test_untrusted_container_guard.py)
  and [`tests/test_note_authority_adversarial.py`](../tests/test_note_authority_adversarial.py):
  untrusted text-layer and forged-note controls.

Hidden answer-key verdicts are excluded from field extraction and do not change
adjudication. Hidden-span presence remains visible in the ledger and may enter
confidence features; the verdict itself is not decision evidence. The red-team
claim is scoped accordingly: hostile twins preserve emitted fields and
adjudication, except the intentionally evidence-withheld case, rather than a
blanket byte-identity claim about every ledger or confidence field.

## 4. Inspect safety boundaries

- [`mib/flagread.py`](../mib/flagread.py),
  [`mib/worldread.py`](../mib/worldread.py), and
  [`mib/sponsorread.py`](../mib/sponsorread.py) emit only adverse evidence.
- [`mib/feeread.py`](../mib/feeread.py) requires positive visual evidence before
  an approval-adjacent `paid` read.
- [`mib/noteread.py`](../mib/noteread.py) recovers only deny/review directions by
  default; approval recovery remains disabled.
- [`tests/test_final_consistency.py`](../tests/test_final_consistency.py) covers
  both ordinary contradiction demotion and the rank-1 exception.
- [`tests/test_native_sanitization.py`](../tests/test_native_sanitization.py) and
  [`tests/test_two_ledger_gates.py`](../tests/test_two_ledger_gates.py) cover
  native-field validity and monotone fusion.

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
  prediction refresh, and batch governor.
- [`tests/test_watchdog.py`](../tests/test_watchdog.py) covers worker death,
  lower-level hangs, and one-case recycling identity.
- [`tests/test_governor.py`](../tests/test_governor.py) covers governor
  transitions and level-0 equivalence.
- [`tests/test_merge_case_retries.py`](../tests/test_merge_case_retries.py)
  covers retry selection and merge behavior.

Determinism is claimed only for fixed inputs, image, configuration, and governor
behavior. At governor level 0, the path is output-identical to the ungoverned
path. A changing governor schedule or deep timeout-boundary stress may send
different cases through reduced OCR work, so cross-schedule byte identity is
not claimed.

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

## 7. Final identity check

`SUBMISSION.md` intentionally contains source and prediction-hash placeholders
while the final release is being assembled. A release is not complete until
both are replaced with the exact clean-run identities. This check must print no
matches:

```bash
rg -n 'FINAL_RELEASE_SOURCE_SHA|FINAL_PREDICTIONS_SHA256' \
  README.md SUBMISSION.md MEMO.md docs/
```

The public proof surface is therefore: source, tests, committed adversarial
corpus, the visible-evidence forensic, dependency/model provenance, the final
public Git commit, and the submitted prediction hash. Private review kits,
cached states, or unpublished experiment receipts are not required to accept
the public claims above.
