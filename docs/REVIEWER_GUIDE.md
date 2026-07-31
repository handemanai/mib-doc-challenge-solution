# Reviewer guide — verify the claims in 15 minutes

Everything in `MEMO.md` is backed by an artifact in this repository. This page
maps each claim to the fastest way to check it.

## 1. Reproduce one packet in 60 seconds

```bash
docker build -t mib-submission .
mkdir -p /tmp/one /tmp/out && cp <train_dir>/MIB-000001.pdf /tmp/one/
docker run --rm --network none --cpus 4 --memory 8g --read-only --tmpfs /tmp \
  --mount type=bind,src=/tmp/one,dst=/input,readonly \
  --mount type=bind,src=/tmp/out,dst=/output \
  mib-submission /input /output/predictions.jsonl
```

Two runs produce byte-identical output; the full 5,000-case validation run is
one uninterrupted run of the same prediction entrypoint (`scripts/predict.py`,
which `run.sh` execs).

## 2. The trap suite proves itself

`tests/redteam_corpus/` contains a self-authored corpus of every injection
vector the field manual names but the public PDFs omit — white-on-white and
render-mode-3 answer keys, off-crop text, zero-opacity fills, hidden OCG
layers, QR instructions, under-image text, microtext — each paired with a
clean twin. The pytest suite (`tests/test_redteam.py`) asserts each
trapped packet produces output identical to its twin: the injections are not
merely resisted, they are provably invisible to the decision path. The
runtime contains no component that follows instructions (no LLM/VLM), so the
instruction-injection surface this dataset targets does not exist.

The injections are not hypothetical: 216 of the 1,000 training packets
(21.6%) carry a hidden answer key — its adjudication wrong in all 216 — and
our span forensics flags a similar rate (~25%) across the validation set.
A cross-submission census shows most
public entries follow it on 10%+ of those cases, versus 2.6% incidental
agreement for this pipeline. On MIB-102051 a 76% majority of public entries
deny — the hidden key's verdict — while the visibly printed registry line
reads `Registry Status: CLEAR`.

## 3. The one false approval is proven irreducible, not excused

`experiments/CFA-MIB-000865-visible-forensic.md` documents the audit of every
channel the true visa class could occupy on MIB-000865 — text layer,
native-resolution OCR, hidden/off-crop text, annotations, optional-content
groups, embedded files, cross-field consistency, near-white wash reveal — and
its absence from all of them, plus the control packet showing that
"find the washed clue" is itself a planted trap on approval-side packets.

## 4. Safety architecture is structural, not statistical

- Deny-direction ROI readers cannot emit approval-moving values by
  construction (`mib/flagread.py`, `mib/worldread.py`).
- Approval-adjacent reads face positive-evidence bars
  (`mib/feeread.py`: "paid" requires the "un" region provably clean).
- Every APPROVED row is re-adjudicated against the exact fields it emits
  before it is written (`mib/two_ledger.py`,
  `enforce_final_consistency`) — the submission cannot print an
  approval whose own evidence demands denial or review.
- `NEEDS_REVIEW` on evidence-withheld packets is the designed-correct output,
  confirmed by the organizers (challenge issue #5).

## 5. Honest measurement

Tuning used a fixed 799-case split; the 201-case holdout was read only at
milestones. Negative results are retained rather than discarded:
approaches measured and rejected include an ML hedge-resolution gate (−4
OOF), a +90-raw-EV approval expansion declined for manufacturing systematic
false approvals, and a trained OCR-correction transducer that ships disabled
after losing on the sealed holdout under its pre-registered gate.

`docs/PERFORMANCE_OPPORTUNITY_REGISTER_2026-07-26.md` is the dated register
of the opportunity portfolio with each item's measured ceiling — including
the ones we chose not to take and why; its closing addendum (2026-07-31)
records the final measured declines, summarized in section 6 below.
`experiments/CFA-MIB-000865-visible-forensic.md` is the full irreducibility
forensic behind section 3.

## 6. Appendix — negative results and declined techniques

The thesis this appendix documents: the remaining gap between this submission's
score and 150 is measured to be dominated by information physically absent from
the packets, and every shortcut across it manufactures catastrophic false
approvals. Each technique below was built, measured, and declined, with the
numbers that forced the decision.

**Learned NEEDS_REVIEW resolvers — the field's dominant technique.** Four
public entries score above our train number by applying a learned review
resolver to our own published baseline (commit `4b37a78`, MIT, attributed). We
replicated the approach against our own 258 eligible hedges (closing receipt,
2026-07-31): applied in-sample it shows **+4.83** total points at **13**
catastrophic false approvals; under honest 5-fold out-of-fold evaluation —
their exact architecture, three fold-seeds — it yields **+1.35 to +2.75**
total at **3–25** new false approvals per 1,000 cases depending on guard. No
operating point is false-approval-clean: the approve-only conf ≥ 0.695 guard
that shows zero false approvals in-sample mints 3–8 out-of-sample. Declined.
Every NEEDS_REVIEW we emit is a case where the visible evidence genuinely
under-determines the outcome.

**Hedge conversion by confidence threshold.** Converting hedges above a
confidence cut measures **+2.48** on train at **34** false approvals; the
coarser remap NR & conf < 0.5 → APPROVED nets **+0.075** while moving false
approvals from 1 to 43. Both declined.

**Approval heads for unread fee/flags.** A fee dark head measures **+0.946**
while moving false approvals from 1 to 3; a flags head (never shipped;
reconstructed for measurement) **+0.65–0.77** at 1 → 11. Both sit behind
default-off flags; both OFF.

**Calibration transforms.** The fitted temperature is the identity and every
transform family is negative under cross-validation; the oracle isotonic bound
is **+0.049**. The calibration head is at its measured ceiling.

**Info-bound proofs for the residual.** The residual is absence, not
misreading. Of 35 deny-hedge flag cases, 14 have no scan surface at all; on
the 21 where the ROI gate was attempted and failed, a truth-word template
sweep peaks at 0.41–0.61 versus 0.38–0.63 for truth-none controls (n = 21 vs
30) — indistinguishable from noise. POL-12 dual fee-clearance is
generator-impossible: 0/1,000 training packets carry two fee-bearing
surfaces, and an exhaustive 4,096-conjunction zero-denial search returns
empty. A 40-case hedge audit finds 37 information-absent, 3 policy-correct
declines on untrusted surfaces (SAMPLE DENIAL, ARCHIVE, hidden text), and 0
clean misreads. The fee residual's mechanism is absent waiver evidence —
86/123 fee misses are truth "waived" with the waiver-code page absent, and
the candidate pool is empty on 96/123 — not "unreadable unknown".
