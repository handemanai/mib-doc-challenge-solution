# MIB Doc Challenge — Technical Memo

On a fixed 799/201 split of the public training set, with the holdout inspected
only at milestones, the release lineage
measured **129.52 on development and 126.46 on holdout**, with zero catastrophic
false approvals on holdout and one on development.

## Approach

The offline, CPU-only system extracts nine fields
from each PDF, applies deterministic evidence and policy rules, and then computes
a calibrated confidence for the resulting decision. Expected-value calculations
were used offline to compare candidate policy changes against the competition's
scoring matrix; they do not choose production decisions.

**Forensics before OCR.** In 216 of 1,000 training packets, the PDF contains a
fake answer key as white-on-white, off-crop, or otherwise hidden text. The system
classifies spans by render mode, opacity, colour, size, crop position, and draw
order, then removes hidden spans before raster enhancement. The hidden answer-key
verdict is not parsed into fields or used to change adjudication. Hidden-span
presence remains audit provenance and a confidence feature. Masking prevents
contrast enhancement from resurrecting invisible text. With no LLM, VLM, or
other instruction-following component, prompt following is not a runtime path;
evidence poisoning remains and is handled by page binding, source ranking, and
review gates.

**OCR and structured extraction.** RapidOCR uses an ONNX English mobile
recognizer at a low-resolution fast path. Packets still missing deny-relevant
fields can receive a higher-resolution pass because the six-second constraint is
an average across PDFs. Native text pages bypass OCR. Values are normalized and
snapped to legal vocabularies where appropriate; margin and agreement across
sources become quality features. Template-specific readers recover evidence
whole-page OCR misses. Their authority is asymmetric:
readers allowed to be aggressive can emit only adverse evidence, while
approval-adjacent reads require positive evidence. For example, “paid” is
accepted only when the region where the `un` in “unpaid” would appear is visibly
clean.

**Two physical views, two ledgers.** Scanned packets also receive a
native-resolution pass over embedded scan images. It is extracted and
adjudicated independently from the composited PDF view. A frozen selector can
replace a weak field with stronger native evidence, but fusion never creates an
approval. Explicit native adverse evidence can narrow `NEEDS_REVIEW` to `DENIED`;
otherwise the baseline decision remains authoritative. Conflicting rank-1 note
views force review.

**Deterministic adjudication, then confidence.** The production policy combines
the field manual with public-training rules that survived held-out checks. Given
true fields, it reproduces 97.3% of training adjudications with zero
APPROVED/DENIED confusions. A post-fusion check re-adjudicates every approval
against the exact emitted fields. Ordinary contradictions narrow to
`NEEDS_REVIEW`. The deliberate exception is an exact, case-bound, signed rank-1
adjudicator finding: the manual gives that evidence higher authority than
ordinary fields, so a conflicting approval can remain approved and the conflict
is recorded. Rank-1 findings may control adjudication while conflicts remain
recorded; emitted fields change only when the note contains an explicit field
correction.
Only after this policy path is fixed does the logistic/isotonic calibrator compute
confidence from evidence quality and decision-path features.

## What measurement changed

The largest residual initially looked model-shaped. A direct census instead
showed that 31–41% of fallbacks already had the true text in the visible OCR
stream: the parser, not the recognizer, was failing. Six deterministic parser
repairs were worth about 2.4 points.

An ML hedge resolver scored four
points worse out of fold and created 32 catastrophic false approvals. An
approval expansion for otherwise-clean cases with unread flags had positive raw
expected value but created 19 systematic false approvals, so it was rejected.
A 2.6-million-parameter OCR correction model improved isolated string pairs but
measured +0.04 on development and -0.05 on holdout; it ships disabled. These
experiments are why expected value remains an evaluation tool instead of a
production decision layer.

## Robustness and runtime

The committed red-team corpus covers hidden and off-crop text, render-mode-3,
zero opacity, hidden optional-content layers, under-image text, microtext,
visible decoys, sample-denial watermarks, and QR instructions. Tests require
hostile packets to preserve the clean twin's fields and adjudication, except
where visible evidence is intentionally absent, and prevent hidden tokens from
entering extracted fields.

Each PDF has a SIGALRM deadline. A parent heartbeat watchdog replaces a worker
hung below Python's signal layer, and workers actively recycle after 48 completed
cases to avoid observed native-library lifetime failures; completed states are
flushed and `fsync`ed first. A batch governor estimates finish time and, only on
hardware trending beyond the limit, reduces future OCR work in measured stages.
At level 0 it is output-identical to the ungoverned path. When the governor is
inactive—or its level and all runtime conditions are fixed—repeat runs are
deterministic. Deep timeout-boundary stress can change which cases receive a
reduced path, so determinism is not claimed across changing schedules.

The last completed scoring-contract measurement used four workers: 3.43 seconds
per PDF, about 17,100 seconds for 5,000 PDFs, 3.3 GiB peak RSS, a 0.30 GiB image,
and 12 MB of model artifacts. The uninterrupted validation run completed in 4
hours 4 minutes with zero timeouts, retries, or governor engagements. It ran on
Apple silicon; a `linux/amd64` image build and sample output were separately
checked. No cross-architecture speed equivalence is claimed.

## Failure boundary

The development false approval, MIB-000865, visibly prints `Visa Class: XW-2`
while the label says `TRANSIT-7`. The true value was absent across the audited
visible-evidence channels. Demanding extra visa corroboration would hedge 26
approvals, 25 correct, to prevent this one. I kept the evidence-respecting policy
and documented the limitation rather than fitting a case identity or hidden
surface. The larger residual is missing evidence: many packets contain no flags
surface at all, for which `NEEDS_REVIEW` is the intended action rather than a
guess from generator priors.

## With another week

I would extend the Reason-line reader for the four tracked rasterized notes it
currently skips, but only behind the same case-binding and zero-regression gates;
build a distinct faint-ink restoration view for human-legible note text below
the current OCR signal floor; and expose per-field confidence rather than only a
row-level value. I would also rerun a larger grouped perturbation campaign across
page types and damage modes. I would not add a learned `NEEDS_REVIEW` resolver or
any case-identity prior: both substitute generator regularities for missing
visible evidence, and the existing out-of-fold experiments show the false-
approval cost.

## A note on the author

I am a practicing surgeon, not a software engineer, and I am not entering this
competition as a job application. I wanted to test honestly how far one person
could take agentic coding on a difficult, adversarial problem. AI wrote nearly
all of the code. I owned the problem framing, evidence standards, experiment
design, promotion gates, and final decisions: what counted as trustworthy,
which shortcuts were unacceptable, and when a measured gain was not worth its
failure mode. That division of labour is part of the experiment, and I want the
submission to be evaluated with it stated plainly.
