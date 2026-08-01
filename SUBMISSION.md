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
review gates. A hidden answer-key verdict does not change emitted fields or
adjudication.

## Runtime contract

- Entrypoint: `<input_pdf_dir> <output_predictions_path>`.
- Verified run flags: `--platform linux/amd64 --network none --cpus 4
  --memory 8g --pids-limit 512 --read-only --tmpfs /tmp:size=2g`.
- Runtime stack: RapidOCR/ONNX plus classical PDF, image, parsing, and policy
  code. The optional candidate-trained character transducer ships disabled.
- Last completed release-lineage measurement: 3.43 s/PDF, approximately 17,100
  seconds for 5,000 PDFs, 3.3 GiB peak RSS, 0.30 GiB image, 12 MB total model
  artifacts, and 7.9 MB largest artifact.
- The uninterrupted 5,000-case run completed in 4 h 04 m with zero per-case
  timeouts, zero retries, and zero governor engagements.
- Each case has a deadline; a parent heartbeat handles lower-level hangs; active
  worker recycling replaces each worker after 48 cases; and the batch governor
  can reduce future OCR work if projected runtime approaches the hard limit.
- At governor level 0, fixed inputs/configuration, and the same image, repeated
  runs are output-identical. Determinism is not claimed across different
  governor schedules or timeout-boundary stress.

## Reproduce and validate

Set `CHALLENGE_DIR` to an absolute checkout of the official challenge repository.
Run these commands from this solution repository:

```bash
CHALLENGE_DIR=/absolute/path/to/mib-doc-challenge
OUTPUT_DIR=/tmp/mib-submission-output
mkdir -p "$OUTPUT_DIR"

docker build --platform linux/amd64 -t mib-submission .
docker run --rm --platform linux/amd64 \
  --network none --cpus 4 --memory 8g --pids-limit 512 \
  --read-only --tmpfs /tmp:size=2g \
  --mount type=bind,src="$CHALLENGE_DIR/data/validation",dst=/input,readonly \
  --mount type=bind,src="$OUTPUT_DIR",dst=/output \
  mib-submission /input /output/predictions.jsonl

python3 "$CHALLENGE_DIR/scripts/validate_submission.py" \
  --submission "$OUTPUT_DIR/predictions.jsonl" \
  --manifest "$CHALLENGE_DIR/data/validation_manifest.csv" \
  --require-complete
```

The submitted prediction file lives in the challenge repository under
`submissions/handemanai/`; it is not duplicated here.

## Final release identity

The release coordinator must replace the following two explicit placeholders
after the final clean-image run and before submission. They are intentionally not
presented as completed provenance:

- `FINAL_RELEASE_SOURCE_SHA` — public solution commit used to build the final
  image.
- `FINAL_PREDICTIONS_SHA256` — SHA-256 of the final 5,000-row
  `predictions.jsonl`.

The most recent completed predecessor artifact contained 5,000 valid records,
zero missing cases, and had SHA-256
`6d51c904f006b80de9a7140c27ac8852776fd12b11b49f34a25214101ebe374a`.
That predecessor is a rollback artifact, not the identity claim for the final
release.

## Authorship

I am a practicing surgeon, not a software engineer, and this is an experiment in
agentic coding rather than a job application. AI wrote nearly all of the code. I
set the goals, evidence standards, experiment boundaries, and promotion
decisions, including rejecting apparent score improvements that created unsafe
or poorly generalizing behaviour. I am stating that division honestly so the
work can be judged for what it is.

See `MEMO.md` for the technical argument and `docs/REVIEWER_GUIDE.md` for a map
of claims to public source and tests.
