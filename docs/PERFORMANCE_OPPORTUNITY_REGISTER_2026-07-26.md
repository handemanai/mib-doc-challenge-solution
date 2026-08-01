# MIB Performance Opportunity Register

> **Historical research log, not final-release proof.** This dated working
> register preserves hypotheses, gates, and terminal dispositions from private
> development. Some referenced receipts and intermediate files are intentionally
> absent from the public repository. An absent artifact is unavailable evidence,
> not a public verification claim. Current release claims and publicly tracked
> evidence are mapped in [`REVIEWER_GUIDE.md`](REVIEWER_GUIDE.md).

Date opened: 2026-07-26
Program objective: win the MIB document challenge with a visible-evidence,
private-test-resilient, reproducible system.
Scope: performance, robustness, calibration, runtime allocation, and technical
elegance. Submission-form, PR-body, and administrative cleanup were handled
separately and are out of scope for this register.

This file is the durable index for the full opportunity portfolio derived from
the 2026-07-26 external competitive review. No item disappears because it is not
deadline-critical. Every experiment must end in `SHIP`, `PARK`, or `REJECT` with
an immutable receipt under `experiments/receipts/`.

Reconciliation snapshot: committed source `b9a33c6` plus the full 1,105-line
source report. This pass changes portfolio bookkeeping only. It does not claim
that an uncommitted or temporary experiment ran, does not rewrite historical
receipts, and does not convert diagnostic evidence into promotion evidence.

> **Provenance note (2026-07-31).** This register is a point-in-time snapshot of
> the private experiment tree's tracking board, published so reviewers can see
> the full opportunity portfolio, including the directions we measured and
> declined. Commit hashes cited in individual rows (`b9a33c6`, `441709c`,
> `f580782`, `e6c7519`) and file paths under `experiments/receipts/`,
> `docs/REG_15A_V2_DEBUG_OUTCOME.md`, and
> `docs/ACTION_PROVENANCE_AND_DECISION_FEATURES_V3_CONTRACT.md` refer to that
> private tree and are not present in this repository. The one judge-facing
> forensic artifact is included here as
> `experiments/CFA-MIB-000865-visible-forensic.md`.

## Status vocabulary

- `CONFIRMED`: repository/public evidence establishes the premise.
- `PARTIAL`: part of the premise is established; important qualifications remain.
- `UNVERIFIED`: useful hypothesis requiring a controlled audit.
- `STALE`: source observation is no longer current.
- `GO`: authorizes only the explicitly named bounded next activity. It is an
  interim orchestration state, never an experiment outcome, `SHIP`, promotion,
  or permission to bypass a dependency, stop gate, or immutable receipt.
- `SHIP`: passed the experiment contract and is integrated.
- `PARK`: plausible, but proof, time, runtime, or sample support is insufficient.
- `REJECT`: failed a safety, generalization, score, provenance, or runtime gate.
- `NO-GO`: prohibited by the evidence boundary or competition rules.

`PARK` and `REJECT` always apply to the named mechanism, input distribution,
and scope. A materially different continuation needs its own identity and
dependencies; it does not erase or reinterpret the prior result.

## Non-negotiable doctrine

1. Hidden answer keys, hidden field values, barcode instructions, filenames,
   PDF hashes, case IDs, and generator signatures are never field or policy
   evidence.
2. Approval requires affirmative, visible, case-bound clearance. Missing evidence
   cannot become clearance.
3. Approval-creating changes require zero new catastrophic false approvals in
   every grouped campaign and perturbation suite, plus a conservative denied-risk
   upper bound.
4. Denial-only readers still require causal visible evidence and a zero-new-wrong-
   denial gate; "cannot create an approval" is not synonymous with harmless.
5. Field-only experiments byte-freeze adjudication and confidence.
6. Validation PDFs may be used only for predeclared aggregate, label-free shift
   diagnostics. No per-case correction, pseudo-labeling, or architecture tuning
   from individual validation outputs.
7. Public scores are directional evidence, not private-validation truth.

## A. Control, evaluation, and provenance

| ID | Opportunity | Premise | Current status | Dependency | Disposition |
| --- | --- | --- | --- | --- | --- |
| CTRL-01 | Durable opportunity/experiment board | Rich source analysis must not be lost between working sessions | SOURCE INVENTORY LOSSLESS AT `b9a33c6`; OUTCOME RECONCILIATION CONTINUES | CTRL-03 for canonical receipt/index parity | PRESERVE this board as the source-of-truth opportunity inventory; individual rows still require their own terminal receipts |
| CTRL-02 | Immutable experiment receipts | Scores without source/config/group identity are not decision-grade | PARTIAL; PRODUCTION SCOPES EXPLICITLY FAIL-CLOSED | standardized-v2 receipt plus semantically replayed mechanism evidence | `evaluation_only` and `safety_only` retain their existing gates; `field_only`, `calibration_only`, `reader`, `approval`, and `architecture` cannot SHIP from hash-bound claims and remain PARK until their exact artifacts are parsed and outcomes recomputed |
| CTRL-03 | Reconcile the register, receipt index, and live portfolio | A stale tracking surface can silently lose a negative result, dependency, or still-uncommitted receipt | DOCS RECONCILED THROUGH `b9a33c6`; CANONICAL INDEX STILL STALE | separately authorized historical-receipt reconciliation, mechanism-aware outcome receipts, and a regenerated deterministic portfolio index | PARK canonical closure: the standard index check still stops on a stale ARB-01 contract hash and the hash-skipping check reports a stale generated index; this docs-only pass changes no receipt and proves no experiment outcome |
| EVAL-01 | Repair large-run evaluation orchestration | Current workers retire after 48 cases but `eval_split` did not respawn them | PARTIAL LIVE PROOF | terminal matched RUN-08 rescue/identity evidence, then a fresh exact official-config 1,000-case run | Planned recycling and fresh retry processes worked, and incomplete extraction failed closed; the fc8 label-free run produced 998 successful states but no terminal cache because `MIB-000796` and `MIB-000989` exceeded both standard attempts. RUN-08 is now the bounded critical-path continuation for reproducing completed attempt-1 OCR work inside attempt 2; implementation alone is not outcome evidence |
| EVAL-02 | Production two-ledger perturbation path | Prior perturbation decisions were single-ledger | CONFIRMED | clean container replay | PARK outcome execution: the exact production two-ledger transition schema, same-byte pairing, and receipt-bound runner are fail-closed verified; all frozen artifacts remain unexecuted pending committed distinct clean source identities and rebuilt pinned images |
| EVAL-03 | Layout-family grouped campaign | V1 label-blind bootstrap is reproducible but fragmented into 921 provisional groups | USABLE WITH SCOPE | outcome-scored grouped campaign | PARK: v3 preserves the exact 724-family v2.1 visible-layout anchor; templates remain fold-local |
| EVAL-04 | Packet-topology grouped campaign | V1 visible-structure bootstrap yields 231 provisional groups | USABLE WITH SCOPE | outcome-scored grouped campaign | PARK: v3 preserves the exact 112-family structural anchor and freezes an 811-family baseline-derived visible-page-type/name-cardinality proxy as diagnostic only |
| EVAL-05 | Damage-family grouped campaign | V1 contrast/ink/raster bootstrap yields 628 provisional groups | USABLE WITH SCOPE | outcome-scored grouped campaign | PARK: v3 preserves the exact 52-stratum physical anchor and freezes a 49-family baseline recovery/quality proxy as diagnostic only, not causal damage truth |
| EVAL-06 | Generator-batch blocked campaign | 110 exact metadata families are not defensible generator batches | BLOCKED | independent visible batch source | PARK: v3 keeps the one-family generator anchor blocked; case ranges, filenames, timestamps, and hidden fields were not substituted for identity |
| EVAL-07 | Semantic cold-start panels | Sponsor/world/purpose/name/reason recurrence may masquerade as reading | DIAGNOSTIC ONLY | prospective label-blind extraction | PARK: 1,000-state pre-truth domain-hashed panels freeze name 920, purpose 11, sponsor 739, and world 14 groups; extraction dependence bars promotion and reason-template identity remains blocked |
| EVAL-08 | Legacy public-train quarantine panel | The public training corpus and legacy 201-case split were already inspected at multiple milestones | HISTORICAL; PERMANENTLY UNAVAILABLE AS PROSPECTIVE | none | Preserve for historical comparison only; never relabel another inspected public-train subset as sealed |
| EVAL-08F | Future prospective panel | A genuinely prospective panel can still test late-stage robustness if its identity is frozen before any outcomes are observed | UNRUN/CONDITIONAL | organizer-private data or a write-once future perturbation seed frozen before execution; no public-train reselection | PARK until an eligible future source exists; this is a distinct experiment and cannot retroactively validate EVAL-08 |
| EVAL-09 | Nested grouped calibration | Current random-fold isotonic fit is not nested | CONFIRMED | complete feature matrix | PARK: nested arbiter mechanism implemented |
| EVAL-10 | Overall and worst-group scorecard | Aggregate score hides safety and tail failures | CONFIRMED | promotion-grade group campaigns | PARK: receipt-bound v2.1-anchor scorecard implemented and exercised on 1,000 cached rows; the first diagnostic had 0 changed cases and 0 score delta while all core gates passed, so it validates reporting only; actual treatment evidence and v3 diagnostic-panel reporting remain pending |
| EVAL-11 | Historical aggregate train/validation shift census | Existing validation ledger can reveal systemic shift | PARTIAL/HISTORICAL: prior diagnostic is source/config-mismatched and the committed v1 metric surface is incomplete | EVAL-21C complete aggregate contract for any fresh run | PARK: preserve the prior diagnostic as historical only; no fresh 5,000-case extraction may use its incomplete metric surface |
| EVAL-12 | Paired deterministic baseline/treatment runs | Reader changes need exact attribution | CONFIRMED | clean committed source | PARK outcome execution: the exact production two-ledger transition schema, same-byte pairing, and receipt-bound runner are fail-closed verified; all frozen artifacts remain unexecuted pending committed distinct clean source identities and rebuilt pinned images |
| EVAL-13 | Separate known-template damage and unseen-layout tests | Registration on a known family is not unseen-layout generalization | CONFIRMED | EVAL-03 | PARK: a separate visual-degradation suite is frozen, but the one-source infrastructure smoke is not an unseen-layout or performance result |
| EVAL-14 | Runtime-tail scorecard | Mean runtime hides p95/p99/max and lifecycle failures | CONFIRMED | timing telemetry | PARTIAL MEASUREMENT: the bound 1,000-case root extraction reports p50 28.8685 s, p95 111.02205 s, p99 233.63793 s, max 641.506 s; exact pinned/native batch wall time, RSS/storage, treatment timing, and reader-local timing remain PARK |
| EVAL-15 | Label-preserving visual campaign | Visual robustness must preserve label and evidence semantics | CONTRACT + RUNNER VERIFIED | committed clean paired execution | PARK: three artifacts frozen; no outcome, label, or score run |
| EVAL-16 | Evidence-destroying monotonicity | Removing evidence must not open approval or be scored against the stale old label | CONTRACT + RUNNER VERIFIED | committed clean paired execution | PARK: three transition-only masks frozen; decisive evidence remains unverified and no outcome run exists |
| EVAL-17 | Trust/adversarial campaign | Hostile document surfaces must not authorize actions or inflate support/confidence | CONTRACT + RUNNER VERIFIED | committed clean paired execution | PARK: three hostile-vector packets frozen; authority/preservation outcomes are unrun |
| EVAL-18 | Reason-template semantic holdout with visible-only reason control | Recurring decision-reason wording can masquerade as generalization, but the current reason surface is extraction-dependent and not an independent visible identity | UNAVAILABLE/UNVERIFIED | pre-truth, visible-only reason-source control independent of truth labels, terminal action, and model output | PARK; never derive a grouping or predictor from adjudication truth, terminal reason, or post-outcome text |
| EVAL-19 | Causal input-byte damage-family campaign | Current physical/operational proxies do not isolate JPEG degradation, washout, smudge, field cut-out, or ruled-line interference as causal input families | UNDERREPRESENTED | predeclared label-preserving transforms or independently measured visible input-byte damage, then distinct-state outcome scoring | PARK pending frozen causal families; do not promote from baseline recovery/quality proxies |
| EVAL-20 | Distinct-state grouped scorecard | Same-state replay validates reporting but cannot measure a reader, policy, arbiter, or scheduler treatment | IMPLEMENTED + INDEPENDENTLY REVIEWED; RUN-09 HAS A REAL 48-CASE SAME-STATE PAIR; DISTINCT-STATE OUTCOME UNRUN | committed baseline/treatment states from distinct source identities, same input bytes, v3 groups, receipt-bound outcomes, and mechanism-specific semantic revalidators | PARK: the RUN-09 pair proves exact-product identity and diagnostic runtime behavior only; it is not a distinct-state score result and does not close reader, policy, arbiter, scheduler, or promotion gates |
| EVAL-21C | Complete aggregate shift and resource-telemetry freeze | The committed v1 census omits stable page-type/template incidence, OCR-confidence distribution, broad damage statistics, native/composited disagreement, registry-phrase incidence, unknown-layout incidence, runtime tails, CTC/OCR disagreement, and the complete EVAL-22 resource publication surface | CONTRACT EXTENSION REQUIRED; CURRENT TOOL INCOMPLETE | before validation extraction, freeze every report metric plus wall time, mean elapsed runtime/PDF, mean CPU time/PDF or explicit CPU unavailability, p50/p95/p99/max, peak RSS, temporary/final storage, model/image size, retries, failures, and reserve as implemented or explicitly unavailable, with exact collectors/keys/units/denominators/missingness and source/config-compatible inputs | PARK; no 5,000-case run may start with the incomplete v1 surface. EVAL-21 shift and EVAL-22 resources are sibling outcomes of the same run; unavailable metrics remain named limitations |
| EVAL-21 | Fresh exact-container 5,000-case label-free shift census | The existing validation diagnostic is source/config mismatched and omits predeclared shift metrics | UNRUN | EVAL-21C terminal contract freeze; clean committed source; exact labeled image; complete fail-closed 5,000-state extraction | PARK; publish only systemic aggregate diagnostics, never per-case correction or pseudo-labeling, and do not run until EVAL-21C closes |
| EVAL-22 | Fresh exact-container 5,000-case completion/runtime/resource audit | A 1,000-case root timing distribution does not establish 5,000-case wall time, lifecycle completion, peak RSS, storage, or reserve | UNRUN | EVAL-21C contract freeze; a fresh exact official-config 1,000-case precursor with zero terminal failures and wall time at or below 4,800 seconds; bound native/resource telemetry on the one terminal 5,000-case execution | PARK; the same 5,000-case execution may supply EVAL-21 aggregate shift and EVAL-22 resource evidence, but no runtime-cap or private-test readiness claim exists until its exact terminal receipt closes |

## B. Semantic integrity and runtime-surface safety

| ID | Opportunity | Premise | Current status | Dependency | Disposition |
| --- | --- | --- | --- | --- | --- |
| SAFE-01 | Ledger audit of approved/rule-trigger rows | Available 5,000-row control has 38/38 legitimate signed rank-1 exceptions; submitted 32 still lack their matching ledger | PARTIAL | submitted evidence ledger | PARK submitted classification; control audit complete |
| SAFE-02 | Rank-1-aware post-fusion invariant | Fields can change after the baseline decision is frozen | CONFIRMED: emitted frequent sponsor, native registry guard, and body-bound rank-1 review all leaked through the field-only final check; review-only closure paired/adversarial proved in `SAFE-02-03-post-fusion-context-closure.json` | paired grouped replay: `full` vs offline-only `full_pre_consistency` on the same durable 1,000 states | PARK integration candidate; can only demote APPROVED to NEEDS_REVIEW, preserves signed authority, never denies or creates approval |
| SAFE-03 | Field/decision trace consistency | Output may be semantically contradictory without a final reconcile | CONFIRMED: exact native decision context now travels with fused output; pre-consistency control reproduces all three erroneous approvals with identical fields | SAFE-02 paired grouped replay | PARK integration candidate; one-mechanism control and eight adversarial provenance rejections unit-proved |
| SAFE-04 | Canonical boolean environment parser | `"0"`, `"false"`, or `"off"` can have inconsistent meanings | CONFIRMED | exact container smoke | INTEGRATION REVIEW: one registry, strict preflight, canonical receipts |
| SAFE-05 | Remove approval-capable dark paths from release surface | Ordinary runtime can contain dormant approval paths absent from receipt allowlists | CONFIRMED | exact container smoke | INTEGRATION REVIEW: EV fee REJECT; note approve/transducer/fee corroborate/anti-oracle and field-only fusion PARK and release-fixed-off |
| SAFE-06 | Bind effective feature flags to every scored run | Commit identity alone does not fix runtime behavior | CONFIRMED | exact container smoke | INTEGRATION REVIEW: all runtime booleans receipt-bound as canonical 0/1 |
| SAFE-07 | Preserve signed adjudicator-note authority | Blanket semantic rules would erase legitimate rank-1 exceptions | CONFIRMED: source-precedence audit found 200/200 signed findings correct | all fusion, OCR-consensus, registered-reader, arbiter, and graph lanes | PRESERVE signed rank-1 authority as a standing invariant; this result does not authorize a broad source-precedence rewrite |
| SAFE-07B | Broad manual/source-precedence selector | A generic preference for manual or higher-ranked text can overwrite a current visible source with stale, superseded, or adversarial text | TESTED/REJECTED; DISTINCT FROM SAFE-07 PRESERVATION | sealed source-precedence audit and SAFE-11 visible authority taxonomy | REJECT the broad selector; only a separately provenance-conditioned, case-bound exception may re-enter under a new experiment identity |
| SAFE-08 | Preserve 48-case recycling/fsync/resume | Native/PyMuPDF lifetime cliff is established | CONFIRMED | EVAL-01 | PRESERVE |
| SAFE-09 | Preserve hidden-text-as-distrust-only boundary | Hidden field transcription violates challenge evidence rules | CONFIRMED | all lanes | PRESERVE: trust-suite contract covers OCG, QR instruction, text/raster conflict, foreign/duplicate page, and decoy cases; outcome replay pending |
| SAFE-10 | Preserve direction-asymmetric recovery | Aggressive adverse recovery is the strongest current safety design | CONFIRMED | all readers | PRESERVE: evidence-deletion validator forbids old-label scoring and fails approval-opening transitions; outcome replay pending |
| SAFE-11 | Model document-source precedence before OCR consensus | Stable multi-reader agreement can reproduce visible stale/superseded text that differs from the canonical field | AUDITED: 123 conflicts; wholesale strict rank REJECT, provenance-conditioned native-intake exception PARK | sealed label-after-extraction source audit | PARK |
| SAFE-12 | Complete injection/paint-order preservation surface | Trust safety spans opacity, render mode, crop, paint order, OCG, Unicode, and native/composited separation | CONTRACT + RUNNER VERIFIED | committed clean paired execution | PARK: outcome replay not run |
| CFA-MIB-000865 | Judge-visible recovery of the remaining cached CFA | A remaining error is actionable only if a judge can recover the missing authority from visible evidence | FORENSICALLY CLOSED | exact packet and public truth | REJECT visible reader/ROI recovery and the broad attestation gate: the packet visibly says `XW-2` while public truth says `TRANSIT-7`/DENIED, with no visible correction or adverse authority; PARK the post-hoc singleton and create no production rule |

## C. Visible policy and distributional signals

| ID | Opportunity | Premise | Current status | Dependency | Disposition |
| --- | --- | --- | --- | --- | --- |
| POL-01 | Sponsor-standing phrase census | Exact visible phrase appears in 28/1,000, but only 7 phrase cases overlap the old 201-case production cache; the true-field residual is not the full production residual | CONFIRMED evidence; production residual incomplete | verified v2 1,000-state cache plus frozen exact phrase map | PARK non-DIP exact-deny challenger pending truth-after-freeze counterfactual; PRESERVE DIP no-effect |
| POL-02 | Sponsor phrase by visa class | Diplomatic exemption is exact in public train (5/5 phrase cases approved) | CONFIRMED | none | PRESERVE no-effect DIP exemption |
| POL-03 | Exact/native vs OCR/fuzzy sponsor evidence | No trusted OCR phrase corpus was available and exact text has no positive residual | PARTIAL | trusted OCR evidence | PARK |
| POL-04 | `EMBARGO REVIEW` current-review versus exact-deny policies | Exact phrase appears in 33/1,000, but only 11 overlap the old 201-case production cache; the completed phrase arms compare sponsor denial, registry review, and registry denial rather than the report's score-aware policy C | CONFIRMED evidence; production residual incomplete; score-aware arm not tested | verified v2 1,000-state cache plus frozen exact phrase map | PARK current-review versus exact-trusted-deny counterfactual pending grouped wrong-denial/review-regression evidence; fuzzy or OCR-only phrase remains review |
| POL-04C | Score-aware `EMBARGO REVIEW` evidence-bucket action | The report's policy C selects review or denial from a calibrated posterior over a provenance-qualified exact/fuzzy registry-phrase bucket; it is not the registry-deny arm in the completed phrase counterfactual | UNRUN/EMBARGO REVIEW ARM PRESERVED | provenance-bound exact-versus-fuzzy phrase state, closed ARB-08M, a full-contract ARB-03/07 calibrated posterior with group-disjoint outer predictions, and denial causal-evidence eligibility | PARK; no fit or action change until the full arbiter minimum feature contract closes; ARB-03-RS1 cannot satisfy this dependency, and absence of the phrase never enables approval |
| POL-05A | Sponsor-frequency production decision blocker | Detection varies sharply with batch size/composition and benign frequency is indistinguishable | TESTED/REFUTED by benign and multi-cluster stress | POL-05R, POL-06, POL-07, and POL-08 | REJECT recurrence as a causal production decision blocker; it may neither deny, authorize, nor block approval |
| POL-05R | Sponsor-frequency resampling survival condition | The source report permits recurrence only as a review-direction signal if it survives batch-size, benign-common-sponsor, multi-cluster, and rotated-revocation resampling | FAILED FOR CASE-LEVEL ACTION | POL-06 benign-common-sponsor stress, POL-07 multi-cluster stress, and POL-08 size/recall stress | REJECT case-level review, denial, approval blocking, or authorization from recurrence; retain only POL-05B aggregate diagnostics and the separately clearance-gated, still-unrun POL-12 blocker-removal counterfactual |
| POL-05B | Sponsor-frequency aggregate distribution diagnostic | Sponsor concentration can reveal a systemic batch shift without becoming evidence about any case | CONFIRMED diagnostic premise; no production action authorized | EVAL-21C aggregate-only metric contract and source/config-compatible batches | PARK as a label-free distribution diagnostic only; expose aggregate concentration/cluster incidence without case-level tuning or field/action/confidence effects |
| POL-06 | Benign common-sponsor stress | At N=1,000 even 0.5% benign prevalence triggers and review-blocks five true approvals | CONFIRMED | POL-05A | FAILS causal-evidence gate |
| POL-07 | Multiple recurrent sponsor clusters | Two benign 2% clusters are both detected at N>=200 | CONFIRMED | POL-05A | FAILS private-shift robustness as causal rule |
| POL-08 | Rotated revoked-sponsor stress | Recall is 0 below N=100, about 20% at N=100, and 100% near N=1,000 | CONFIRMED | explicit visible standing evidence | PARK recurrence only as aggregate distribution context under POL-05B; REJECT any case-level decision use |
| POL-09 | Receipt-epoch/date-shift stress | The inclusive day-30 guard closes the 5% boundary CFA; 0/14-day two-vote epoch hulls close the known 10% `+17d` CFA but leave 2/4 CFAs across three deterministic 10% windows and lose up to 8.61 classification points under larger source disagreement | CONFIRMED | `POL-09-date-interval-guard.json`; later durable-state grouped replay only if a truly independent visible date source is found | REJECT three epoch-hull configurations; retain only the existing `age <= -30` integration candidate |
| POL-10 | Preserve phrase absence as non-evidence | Absence of a warning cannot enable approval | CONFIRMED | all policy experiments | PRESERVE |
| POL-11 | Independent visible arrival-date corroboration | The complete cache retains date values and source summaries but 0/1,000 rows retain candidate-level physical page/view/source provenance; the truth-blind fail-closed cohort moved 119 approvals to review, removed 1 CFA, and lost 11.30432 official points with usable worst-group regressions | CONTRACT TESTED; INTENDED MECHANISM PROVENANCE BLOCKED | a new promotion-grade cache with explicit visible, case-bound candidate page plus registered-view provenance | PARK genuine corroboration; REJECT blanket provenance-absence fallback |
| POL-12 | Sponsor-frequency unlock counterfactual | Distribution-dependent recurrence may suppress valid approvals, but removing the blocker is approval-creating | UNRUN/CONDITIONAL | two independent trusted risk-clearance observations, two independent trusted fee-clearance observations, case/view identity, no conflict, grouped and perturbation zero-CFA gates, and an acceptable denied-risk upper bound | PARK until dual trusted clearance exists; frequency alone may neither authorize nor deny |

## D. OCR retry selection and independent consensus

| ID | Opportunity | Premise | Current status | Dependency | Disposition |
| --- | --- | --- | --- | --- | --- |
| OCR-01 | Information-quality retry selector | The natural 17-case R1 replay had no gain; in R2 the existing internal ladder already recovered identical complete fields/APPROVED decisions on affine, rot90, and rot180 | R1 PARK; R2 TESTED IN PINNED IMAGE | a label-blind hard-page corpus where the existing ladder actually fails | R2 REJECT: current content trigger was byte-equivalent in fields/decisions and inference count; strict parse added one rot90 inference with no effect |
| OCR-02 | Page-archetype/label yield score | R2 required a known archetype plus decision-critical structured yield, but changed 0/3 packet fields and 0/3 decisions | R1 PARTIAL; R2 REFUTED ON FROZEN ROTATION PANEL | label-blind failure corpus from durable states | R2 REJECT: no end-to-end gain over the existing ladder |
| OCR-03 | Critical-field and case-ID consistency score | R2 used exact visible body binding only as a safety gate and critical-field yield for routing; all three historical packets were already complete | R1 PARTIAL; R2 TESTED | a genuine residual rotation failure, never case ID as value/policy evidence | R2 REJECT: 0 recovered/lost/changed fields, 0 action changes, 0 approvals created |
| OCR-04 | Confidence-tail/garbage-ratio score | Confidence remained only a late tie-breaker; the strict trigger retried rot90 once but produced the same complete result | R1 PARTIAL; R2 TESTED | residual hard-page corpus and official-runtime timing | R2 REJECT: 19 versus 18 OCR engine inferences over three packets with no field or decision benefit |
| OCR-05 | Targeted Tesseract reader | Current OCR channels share one recognizer family | TESTED ONLY ON THE OLD ANCHORED/STRIP ROI SET | registered authoritative ROI redesign only | REJECT the old anchored-ROI design: 0 incremental correct fields, 4 canonical mismatches; this does not close a registered-crop reader |
| OCR-06 | Tesseract PSM 6/7/11 routing | Three PSM modes were highly correlated on old line strips | REFUTED FOR THE OLD LINE-STRIP ROI SET | OCR-05 redesign | REJECT the old strip matrix only; registered-crop PSM 6/11 remains a separate conditional hypothesis under OCR-15 |
| OCR-07 | RapidOCR raw/HQ/normalized/Sauvola candidates | Preprocessing changed text on 28/44 frozen ROIs but added zero exact fields beyond frozen RapidOCR+CTC; Sauvola was 3 correct/1 wrong | TESTED IN PINNED IMAGE | a genuinely independent reader or registered hard-ROI redesign | REJECT current four-channel matrix: zero incremental exact yield, one cross-view legal disagreement, about 3.50 s/ROI in the emulated pinned-image diagnostic |
| OCR-08 | Current-pool ROVER-style character/token alignment | Character alignment added no exact read over whole-string consensus and worsened accepted errors from one to two on the frozen corpus | TESTED/REJECTED FOR CURRENT SAME-RECOGNIZER VIEWS | frozen current-pool corpus | REJECT current design: 0 incremental, 9 correct/2 wrong versus whole-string 10/1; do not revive it by changing weights on the same outcomes |
| OCR-08R1 | Future independent-reader ROVER continuation | A genuinely independent recognizer may create complementary sequence evidence that was absent from the rejected same-family pool | UNRUN/CONDITIONAL; WEIGHTING CONTRACT FROZEN | a new reader that first demonstrates frozen incremental authoritative yield; source precedence; group-disjoint outer reliability; pre-outcome weights for field-specific engine reliability, preprocessing reliability, OCR confidence, character position, and measured recognizer independence | PARK; align characters/tokens into a confusion network before grammar decoding, use token-set consensus for risk flags, preserve unknown, exclude named source-precedence agreements from votes, and never let same-family agreement independently clear `none` or `paid` |
| OCR-09 | Field-specific reliability weights | Tesseract pilot showed material field-specific error variation and source-precedence conflicts | CURRENT-POOL WEIGHTING REJECTED | genuinely new independent reads | PARK field-specific reliability only for genuinely new independent reads; OCR-13-CS-R1 closes further weighting/re-ranking of the existing pools |
| OCR-10 | Flag token-set consensus | Flags are sets, but no exact token-set consensus survived on any of six frozen flag ROIs | TESTED | genuinely independent flag reader and a larger grouped flag corpus | REJECT current same-recognizer matrix: 0/6 reads, 0 incremental; `none` remains ineligible to clear approval |
| OCR-11 | Independent positive agreement for `none` | Approval-enabling clean flags need positive corroboration; Tesseract provided none | CONFIRMED | genuinely incremental independent channel | PARK |
| OCR-12 | Lower adverse threshold with wrong-denial gate | Multi-PSM adverse consensus produced one canonical mismatch, so current design fails | CONFIRMED RISK | authoritative source precedence | REJECT current design |
| OCR-13 | Production-wide label-blind hard ROI/case census | The verified 1,000-state cache froze 851 hard cases and 2,152 decision-critical field rows before truth; only 2 rows retain reproducible ROI coordinates while 2,150 are case/field candidates, and truth-after-freeze shows 1,019 rows with no correct candidate in either ledger | CENSUS + TRUTH JOIN COMPLETE; PARTIAL ROI EVENT INVENTORY IMPLEMENTED BUT CORPUS UNRUN; CURRENT-POOL SELECTOR REJECTED | run the partial inventory in a new clean cache, then implement the separate append-only every-attempt trace | PARK new candidate generation; partial/local acceptance is not output use or promotion evidence, and no truth/new-reader promotion is allowed before the full trace |
| OCR-13-CS-R1 | Existing-pool candidate re-ranking | A new selector helps only when a correct candidate already exists in the frozen pool | COMPLETE | frozen 1,000-state hard-field truth join | REJECT: only 8/466 current hard-field errors have any correct existing candidate; all three predeclared selectors lose pooled correctness and regress worst groups; the stopping rule forbids another pool-only selector |
| OCR-14 | Independent adjudicator `Finding` reader | The label-free baseline has 342 typed-note cases/557 pages, including 305 incumbent visible rank-1 findings, 12 current recoveries, and 13 residual non-watermarked typed-note cases; current unread-only partial telemetry cannot freeze the preservation cohort, and the exact pinned image contains no independent recognizer beyond incumbent RapidOCR/shared CTC/NCC | READINESS AUDIT COMPLETE; FREEZER DESIGN GO; READER BLOCKED | standalone all-routes pre-truth crop/authority freezer, full physical-source ledger, rebuilt digest-pinned image with a distinct recognizer, zero case-level regressions, and exact fresh-control rank-1/conflict/recovery preservation | PARK treatment; implement/review the freezer, but do not execute or promote a reader until independent-runtime and receipt-closure blockers are removed; neither absence nor a recognized `APPROVED` word may create approval |
| OCR-15 | Registered-crop Tesseract PSM 6/11 | PSM 6 and sparse-text PSM 11 may behave differently after defensible fold-local registration than on rejected line strips | UNRUN/CONDITIONAL | successful registered-crop geometry gate with reproducible ROI hashes and OCR-16 provenance | PARK until eligible registered crops exist; old OCR-05/06 strip failures are not evidence against this input distribution |
| OCR-16 | Promotion-grade ROI provenance cache | New-reader attribution is impossible without every attempted/accepted/rejected crop bound to case, physical page, view, pixels, reader, timing, and final-use reconciliation | PARTIAL ROI EVENT INVENTORY ONLY; FULL APPEND-ONLY EVERY-ATTEMPT TRACE NOT IMPLEMENTED | implement and independently review the full trace, then run a new clean 1,000-state extraction under a distinct analyzer/source identity | PARK; `recorder_complete` means bounded-recorder health only, local acceptance is inventory-only, and no truth join or reader promotion is allowed from Phase A |
| OCR-17 | Information-quality retry residual re-entry | The report's page-archetype, label, field-yield, case-binding, confidence-tail, and garbage-ratio selector remains a valid question only on pages the incumbent ladder actually fails | UNRUN/CONDITIONAL; DISTINCT FROM REJECTED OCR-01–04 R2 | a new label-blind durable residual corpus with incumbent parse-completeness failures, a new frozen experiment identity, and official-runtime timing | PARK; do not retune OCR-01–04 on the already complete rotation panel, and never use case ID as value or policy evidence |

### Frozen future ROVER continuation contract

`OCR-08R1` may start only after a genuinely new recognizer produces incremental
authoritative reads on a frozen corpus. The continuation must normalize without
early legal-value snapping, align characters/tokens, construct a confusion
network, and remain targeted rather than double-OCRing the whole corpus. Before
outcomes it freezes this source-report eligible-field priority:

1. unresolved `risk_flags`;
2. signed adjudicator `Finding`;
3. `visa_class`;
4. `sponsor_id`;
5. `fee_status`;
6. `home_world`; and
7. `arrival_date`.

Changing that scope requires a new experiment identity. For the frozen routes,
the continuation also freezes vote weights for all of:

- field-specific engine reliability;
- preprocessing reliability;
- OCR confidence;
- character position; and
- measured recognizer independence.

Only then may it decode under the field grammar. Risk flags use token-set rather
than whole-string consensus. Benign `none`/`paid` evidence still needs positive
independent agreement and cannot be established by weights or same-family views;
adverse acceptance still carries the zero-new-wrong-denial gate. No weighting
variant may be selected after outcome inspection.

## E. Template registration and visual recovery

| ID | Opportunity | Premise | Current status | Dependency | Disposition |
| --- | --- | --- | --- | --- | --- |
| REG-01 | Label-blind static-layout clustering | Existing pixel readers are sensitive to nuisance displacement | CONFIRMED MECHANISM | grouped OOF field attribution | PARK: isolated probe |
| REG-02 | Fold-local aligned median templates | Static labels/lines can be separated from variable values | CONFIRMED MECHANISM | grouped OOF field attribution | PARK: isolated probe |
| REG-03 | Phase-correlation translation | Coarse displacement should be cheaply recoverable | CONFIRMED MECHANISM | downstream reader gain | PARK: 8/8 induced transforms |
| REG-04 | ECC affine alignment | Small rotation/scale/shear likely dominate residual mismatch | CONFIRMED MECHANISM | downstream reader gain | PARK: held-out known-layout probe |
| REG-05 | Conditional homography | Perspective correction may help a smaller subset | GATED ON 24 hard pages: zero fold-external template assignments, so no justified affine residual | REG-04 residual | PARK: homography was not forced across a failed layout gate |
| REG-06 | Fail-closed registration quality gate | Forced bad alignment can read the wrong ROI confidently | CONFIRMED | grouped unseen-layout evaluation | PARK: unseen layouts rejected in probe |
| REG-07 | Median-template subtraction | Static form ink may be suppressible | MECHANISM IMPLEMENTED | downstream field accuracy | PARK |
| REG-08 | Background division | Faint text may survive better than with absolute subtraction | MECHANISM IMPLEMENTED | downstream field accuracy | PARK |
| REG-09 | Sauvola/local binarization | Damaged document regions may benefit from local thresholds | MECHANISM IMPLEMENTED | registered ROI corpus | PARK |
| REG-10 | Conservative morphology/form-line removal | Ruled lines may obscure characters but erosion can destroy them | MECHANISM UNIT-TESTED; 0/43 hard rows passed the upstream fixed-ROI gate | registered ROI corpus | PARK: no eligible real registered ROI; short-hyphen preservation test passes |
| REG-11 | Registered ROI RapidOCR/Tesseract/CTC | Fixed coordinates reduce localization difficulty | BLOCKED: 0/24 hard pages formed a three-member fold-external template in both layout- and damage-held-out campaigns | REG-06 | PARK: 0/43 field rows eligible; current anchored-ROI CTC rejection does not answer the registered-crop hypothesis |
| REG-12 | Exact-structure HOG/linear readers | Cross-outs/stamps/icons may be recoverable as aligned shapes | AUTHORITY SCOPE SPLIT: cross-outs, exact stamps, biometric icons, embargo regions, and signed findings audited separately; no model fit | authoritative structure audit | PARK each scoped hypothesis; generic red ink remains NO-GO |
| REG-13 | Reject generic red-ink outcome inference | FILED/COPY/decoy stamps cross adjudications | CONFIRMED | all visual readers | NO-GO |
| REG-14 | Faint-ink restoration challenger | Small human-readable/machine-unreadable note subset may remain | BACKGROUND-DIVIDED SAUVOLA PREDECLARED; 0/43 hard rows passed the upstream fixed-ROI gate | ROI corpus | PARK: restoration reader remains unevaluated, not rejected |
| REG-15A | Route-first label-blind geometry census | Existing fixed-ROI work may fail because forms must first be routed by visible structure before fold-local registration | PARK; SECOND STRUCTURAL DESIGN MISMATCH | a separately frozen visible-landmark structural redesign under `REG-18`; this experiment has no further run dependency | Source `441709c` repaired sparse-form eligibility and a non-promotable 200-case debug closed 200/200 workers and verifiers, 177 routed cases, 23 verified zero-route abstentions, 402 routed rows, and 12/12 route controls with zero false accepts; all 99 clean pages populated every fold/type cell, but the frozen descriptor produced 767 clusters with maximum size 3, zero five-member archetypes, and zero executed registrations; all five closest distinct-page registrations failed while 4/4 exact self-controls passed. PARK with no canonical receipt, reader, truth join, threshold widening, minimum-member reduction, or registration-gate relaxation; see `docs/REG_15A_V2_DEBUG_OUTCOME.md` |
| REG-15B | Conditional registered-crop reader screen | Route-first geometry is useful only if eligible registered crops produce incremental exact field recovery | PARK/UNRUN; REG-15A PRODUCED NO VALID REGISTERED CROP | a future separately frozen upstream geometry opportunity must first pass its full support/control gate; implemented and independently reviewed freeze/verify/truth-join command surface; complete append-only crop/reader ledger; immutable pre-truth crops/outputs; separate truth join | PARK: exactly three frozen image configurations (raw, background-divided, and Sauvola) and fixed RapidOCR, Tesseract PSM 7, and current greedy CTC readers remain unchanged; no execution or truth access is authorized without a valid upstream registered crop, and any later screen must reach at least +0.25 total out-of-fold points with no material worst-group loss; fields only, adjudication/confidence frozen |
| REG-16 | Registered NCC/value-template recognition | Registration and background suppression can turn unknown localization into a bounded value choice, but REG-15B freezes only RapidOCR, Tesseract PSM 7, and greedy CTC | UNRUN/POST-GEOMETRY; DISTINCT FROM REG-15B | terminal support from a separately frozen future geometry opportunity, immutable registered crop hashes, fold-local template construction, promotion-grade every-attempt provenance, and a separately frozen truth-later screen | PARK; test NCC/value-template recognition only after the geometry gate, with exact legal-value templates and an explicit unknown/abstain outcome; it cannot be added to or retroactively interpreted as part of frozen REG-15B |
| REG-17 | Registered open/structured-field cohort program | The source report separately proposes registered recovery for date, purpose, and names, while REG-15B's frozen screen does not establish these field-specific cohorts | UMBRELLA ONLY; CHILD COHORTS UNRUN | REG-17D, REG-17P, and REG-17N each close independently | PARK umbrella; no child may inherit another field's eligibility, thresholds, support, or outcome |
| REG-17D | Registered arrival-date cohort | Calendar-valid dates need crop provenance, source authority, and an independent date-specific screen | UNRUN/POST-GEOMETRY | terminal future geometry support; immutable pre-truth date cohort/crops; OCR-16 every-attempt provenance; separate truth join | PARK reader-neutral field cohort; CTC-10 is one optional downstream screen, not a prerequisite. Keep adjudication/confidence frozen and do not treat date plausibility as independent corroboration |
| REG-17P | Registered declared-purpose cohort | Purpose is a closed vocabulary but has lower decision value and distinct private-shift risk | UNRUN/POST-GEOMETRY | terminal future geometry support; immutable pre-truth purpose cohort/crops; OCR-16 every-attempt provenance; private-safe vocabulary; separate truth join | PARK field-only; report purpose independently and require its own support/runtime ceiling |
| REG-17N | Registered applicant-name cohort | Names are open/private-shift-sensitive and a train-derived token list can force unseen names into known values | UNRUN/POST-GEOMETRY | terminal future geometry support; immutable pre-truth name cohort/crops; OCR-16 every-attempt provenance; open-name grammar with explicit unknown; separate truth join | PARK field-only; preserve unknown and never fit target-fold name tokens or templates |
| REG-18 | Visible-landmark structural geometry redesign | REG-15A exhausted a content-sensitive full-raster descriptor and independent cross-page affine alignment design without creating one valid template, while exact self-registration proved the primitive itself is operational | PARK/DESIGN ONLY; NO IMPLEMENTATION OR EXPERIMENT AUTHORIZED | a new source/schema/experiment identity and fresh write-once pre-truth checkpoint using visible landmarks/geometry only; no truth, labels, packet values, candidate outputs, or same-corpus tuning | Re-enter only with at least five distinct fold-external aligned members per template; at least 16 bundles spanning all eight campaign×page-type strata; complete 12 route plus 16 quadrant controls with zero false accepts; unchanged 24 px center, 24 px size, and 0.65 leave-one-out-IoU gates; and, before reader/truth access, each campaign at least 25 distinct eligible cases, two fields, and weighted raw upper bound 225. Do not reuse the REG-15A receipt or treat this as its continuation |
| VIS-01 | Signed `Finding` word HOG/linear classifier | Aligned finding words may provide bounded signed-authority structure distinct from generic ink color | UNRUN/CONDITIONAL | successful registered finding crop, signed-authority provenance, grouped OOF fit, and OCR-14 comparison | PARK; field/authority evidence only and no approval creation |
| VIS-02 | Cross-out/cancellation HOG/linear classifier | A registered cancellation mark can change whether nearby evidence is active | UNRUN/CONDITIONAL | successful registered crop, active/cancelled ground-truth taxonomy, and source-precedence audit | PARK; may change evidence activity only when the authoritative target is identified |
| VIS-03 | Exact authoritative-stamp HOG/linear classifier | Specific stamp shapes may be useful when their authority and meaning are independently established | UNRUN/CONDITIONAL | successful registered crop plus exact stamp identity/authority corpus | PARK exact structures only; generic red ink remains NO-GO |
| VIS-04 | Biometric adverse-structure HOG/linear classifier | A registered adverse biometric icon or structure may expose decision-critical risk evidence | UNRUN/CONDITIONAL | successful registered crop, explicit adverse taxonomy, causal-denial provenance, and zero-new-wrong-denial gate | PARK adverse structures only; absence or unreadability cannot create clearance |
| VIS-05 | `EMBARGO REVIEW` region HOG/linear classifier | A registered exact embargo region may support review routing or targeted field recovery | UNRUN/CONDITIONAL | successful registered crop, visible exact-region corpus, and POL-04 causal-policy boundary | PARK review/recovery use; no generic denial and no approval creation |

## F. Constrained decoding

| ID | Opportunity | Premise | Current status | Dependency | Disposition |
| --- | --- | --- | --- | --- | --- |
| CTC-01 | Direct timestep-probability constrained decoding | Shipped ONNX output is normalized per-timestep class probability, suitable for exact CTC scoring | EXP-12 ANCHORED-ROI DESIGN TESTED/REJECTED; REGISTERED CONTINUATION UNRUN | successful registered-crop signal with an independently frozen continuation | REJECT only the EXP-12 anchored-ROI design: zero incremental correct reads and three wrong legal reads; PARK unchanged constrained scoring on a materially different registered crop |
| CTC-02 | Closed tries for enumerations | Species/world/visa/purpose/fee/flags have legal sets | EXP-12 ANCHORED-ROI DESIGN TESTED/REJECTED; REGISTERED CONTINUATION UNRUN | successful registered-crop signal with private-safe legal vocabularies and explicit unknown | REJECT only EXP-12 thresholded enumeration, which added no signal beyond current ctcscore; PARK a separately frozen registered-crop continuation |
| CTC-03 | Sponsor-ID finite-state grammar | Sponsor IDs have the fixed `SPN-[0-9]{4}` schema | EXP-12 SPONSOR ARM TESTED/REJECTED; REGISTERED CONTINUATION UNRUN | successful registered sponsor crop, exact case/view provenance, and a new frozen screen | REJECT only the EXP-12 sponsor arm: one of four accepted reads was wrong and none was incremental; PARK a separately frozen registered-crop sponsor continuation |
| CTC-04 | Calendar-valid date grammar | Dates have strong structural constraints | EXP-12 ANCHORED-ROI DESIGN TESTED/REJECTED; REGISTERED CONTINUATION UNRUN | successful registered arrival-date crop under REG-17D and the CTC-10 screen | REJECT only the EXP-12 date arm: its one accepted date was already current ctcscore's top legal value; PARK a registered-crop continuation |
| CTC-05 | Name grammar with explicit unknown | Name lexicon helps but private names may be unseen | PARTIAL | successfully registered crop | PARK pending a successfully registered crop; the current registered-reader campaign produced zero eligible fixed ROIs |
| CTC-06 | Legal-value posterior/top-two margin | Conditional legal posterior, absolute score, and top-two margin are now exposed with abstention | EXP-12 MECHANISM TESTED/REJECTED; REGISTERED CONTINUATION UNRUN | successful registered crop plus no more than three newly frozen thresholds | REJECT only EXP-12 strict/permissive gates, which retained the same three wrong legal reads; PARK a separately frozen registered-crop continuation |
| CTC-07 | Preserve unknown under weak legal hypotheses | Grammar must not force hallucinated legal values | CONFIRMED | all decoders | PRESERVE |
| CTC-08 | Independent agreement for `paid`/`none` | Shared-recognizer CTC is not itself independent clearance | CONFIRMED | a future genuinely independent channel; EXP-12 Tesseract was rejected | PARK; same-family CTC can never independently clear `paid` or `none` |
| CTC-09 | Case-ID identity/binding grammar | `MIB-[0-9]{6}` can help bind a visible page to its packet but is not field, policy, or outcome evidence | UNRUN/CONDITIONAL; NOT TESTED BY THE EXP-12 SPONSOR RESULT | a visible registered case-ID crop, packet-manifest binding, ambiguity/duplicate handling, and adversarial foreign-page tests | PARK for identity and conflict routing only; never use case ID as a value predictor, label lookup, policy signal, or approval/denial cause |
| CTC-10 | Registered-crop constrained-decoder screen | The failed anchored EXP-12 design does not answer whether the same legal grammars help after independently valid registration and background suppression | UNRUN/POST-GEOMETRY; DISTINCT FROM EXP-12 | terminal future geometry support; immutable registered crops; separately frozen field membership, legal vocabularies, thresholds, and explicit unknown; OCR-16 provenance; independent truth join | PARK; scope is enumerations, sponsor ID, calendar-valid date, open-name grammar, and case-ID binding only. It remains field/identity-only, cannot force a legal value, cannot count same-family CTC as independent clearance, and cannot retroactively relabel EXP-12 |

## G. Decision theory, calibration, and risk-limiting approval

| ID | Opportunity | Premise | Current status | Dependency | Disposition |
| --- | --- | --- | --- | --- | --- |
| ARB-01 | Reproduce classification+Brier objective | Reported per-case objective is exact only while the evaluator's global calibration floor is inactive | CONFIRMED QUALIFICATION | batch-level scorer parity | PROVEN OFFLINE |
| ARB-02 | Grouped multiclass posterior | Current production chooses rules first and calibrates only chosen-action correctness | CONFIRMED | complete two-ledger feature matrix | PARK |
| ARB-03 | Full-contract multinomial logistic baseline | Small, explainable, CPU-cheap challenger over the complete minimum feature-family contract | MECHANISM IMPLEMENTED; FULL FEATURE SURFACE INCOMPLETE | ARB-08M complete, compatible provenance-complete states, and group-disjoint campaigns | PARK; a reduced-surface run is `ARB-03-RS1` and cannot be reported as this full-contract baseline |
| ARB-03-RS1 | Reduced-surface multinomial logistic diagnostic | The current v3 numeric vector has provenance-safe support/source/view/reader counts, bounded OCR quality, and inventory-only ROI counts but omits several report-required families | BLOCKED/UNRUN; CURRENT FROZEN CONFIG/ANALYZER CANNOT SELF-DESCRIBE RS1 | a new separately frozen execution registration/report schema that emits the exact `ARB-03-RS1` feature-surface label, plus compatible v3 states and the exact feature manifest | PARK; do not fit under legacy `ARB-C0/C1` IDs and relabel afterward, do not close ARB-03 or POL-04C, and make no promotion claim |
| ARB-04 | HistGradientBoosting challenger | Nonlinear interactions may help after a linear baseline | UNVERIFIED/UNRUN | a completed group-disjoint ARB-03 multinomial-logistic baseline and nested model selection | PARK until ARB-03 produces a valid baseline; it is a challenger, never the first fitted arbiter |
| ARB-05 | Hard approval/denial action masks | Posterior must not relearn policy or override evidence doctrine | PROVEN OFFLINE | evidence-gate export | PARK pending data |
| ARB-06 | Hierarchical rare-bucket shrinkage | Sparse reasons/actions need conservative pooling | C2 DESIGN FROZEN; FIT UNAUTHORIZED | independently replayed positive visible-reason control plus grouped OOF predictions | PARK; no fitting entry point exists until the visible-reason control becomes available |
| ARB-07 | Nested action calibration | Current calibration protocol is optimistic | MECHANISM IMPLEMENTED | grouped feature matrix | PARK |
| ARB-08 | Provenance-safe arbiter feature surface and promotion gate | Posterior/action masks cannot infer trusted clearance from aggregate agreement or synthesize missing provenance | CONTRACT CONTRADICTIONS CLOSED; CURRENT V3 IS REDUCED-SURFACE; RS1 SELF-DESCRIPTION BLOCKED; LEGACY V2 CACHE INCOMPATIBLE; GENERATOR CAMPAIGN BLOCKED | v3 action source identity from validated resolved views; future per-observation source/view/authority/value/case binding; the frozen feature-family minimum contract in `docs/ACTION_PROVENANCE_AND_DECISION_FEATURES_V3_CONTRACT.md`; an RS1-aware frozen execution/report identity; causal-reason and signed-rank-1 origin provenance; contract/export parity; all required grouped campaigns | PARK: the pretruth recorder may support a future corpus, but no RS1 fit is authorized until its artifact is self-describing; missing families prevent full ARB-03/POL-04C, inventory counts are not output/action proof, legacy v2 artifacts fail closed, and promotion remains unavailable while generator grouping is unavailable |
| ARB-08M | Full-arbiter minimum feature-family contract | The report's arbiter requires decision/reason, source authority, independent agreement, physical-view conflict, template/layout quality, missing/contested fields, exact/fuzzy policy phrases, biometric/fee completeness, injection/container distrust, date plausibility, and pixel/CTC margins without importing hidden or post-outcome signals | FROZEN INVENTORY; CURRENT V3 PARTIAL | compatible per-observation source/view/authority/value/case binding; exact contract/export parity; every family marked PRESENT, PARTIAL, ABSENT_PARKED, or CONTROL_ONLY_BY_DESIGN; usable grouped campaigns | PARK incomplete families; raw template/group IDs remain grouping controls rather than predictors, and no reduced-surface artifact may close ARB-08M, ARB-03, or POL-04C |
| CONF-C0 | Exact shipped-confidence control | The current confidence path must remain the byte-exact comparator, including floors, reason buckets, and two-ledger behavior | DEFINED | clean 1,000-state cache | PARK pending provenance-safe comparison data |
| CONF-C1 | Provenance-positive confidence | Only authorized, visible, exact, active, case-bound observations that support an emitted field or causal decision reason may increase confidence; missing quality is explicit, never observed zero | DESIGN AUDITED; V3 SOURCE IDENTITY FIXED; NO-RUN | a fresh compatible v3 corpus with selected emitted-value provenance, independently validated action/ROI provenance, and group-disjoint nested calibration | PARK: current global OCR mean rewards unrelated/distrusted scan pages; physical-source identity is no longer the open contract defect, but no fresh compatible selected-value corpus exists |
| CONF-C2 | Final monotone distrust cap | Hidden, OCG, QR presence, foreign/duplicate/unbound pages, conflicts, inactive evidence, and provenance errors may only leave confidence unchanged or reduce it | DESIGN AUDITED; NO-RUN | CONF-C1 plus frozen distrust controls | PARK: must execute after two-ledger reconciliation and every confidence override; trust twins may never raise confidence |
| RLA-01 | Approval-bucket denied-risk estimates | Point accuracy is insufficient for high-stakes sparse buckets | PROVEN OFFLINE | pre-truth approval buckets | PARK pending data |
| RLA-02 | One-sided uncertainty bound | Zero observed false approvals is not a statistical guarantee | PROVEN OFFLINE | RLA-01 data | PARK pending data |
| RLA-03 | Positive clearance/fee/identity/conflict gate | Risk-limiting approval needs explicit evidence completeness | HARD-MASK MECHANISM IMPLEMENTED/SYNTHETIC; REAL COMPATIBLE ROWS UNRUN | fresh v3 SAFE/OCR observation rows | PARK pending real compatible evidence |
| RLA-04 | Score-aware approval must beat review | Operational safety and scorer utility both matter | C1 CHOICE FROZEN/SYNTHETIC; NO OUTCOME | full-contract calibrated posterior and training-side RLA authorization | PARK; reduced-surface or synthetic execution is not outcome evidence |
| RLA-05 | Frozen-group approval-risk bound | Near-duplicate cases inside one layout, topology, or damage family are not independent safety evidence | PROVEN OFFLINE | complete pre-truth approval buckets, explicit action-eligible provenance, and frozen campaign groups | PARK pending complete grouped data and nested risk-coverage curves |
| GRAPH-01 | Small probabilistic evidence graph | Could unify field/source/conflict uncertainty | UNVERIFIED/HIGH RISK | simpler lanes plateau | PARK |
| GRAPH-02 | Per-field posterior, conflict, completeness, and diagnostic adjudication-posterior outputs | Valuable even without graph-controlled decisions | UNVERIFIED | grouped evidence matrix | PARK; adjudication posterior remains diagnostic in the first field-only prototype and cannot control an action |
| GRAPH-03 | Bounded field-only factor-graph trigger | A graph may be justified when simpler provenance-aware selectors plateau and measurable interaction failures remain across candidate selection, page/case binding, source lifecycle, conflict, completeness, or field uncertainty—not only direct multi-source value conflicts | NO EXECUTABLE PROTOTYPE; FULL VARIABLE/FACTOR/OUTPUT INVENTORY FROZEN BELOW | complete candidate-level evidence and source taxonomy; a predeclared interaction-error census; at least +0.10 relevant-section recoverable opportunity across one or more retained graph outputs; simpler-lane plateau | PARK P3; first prototype is offline field-only and cannot control adjudication. Calibration-only or action-consistency opportunity may justify a later separately identified diagnostic, but any architecture or action-control proposal still requires at least +0.50 total points plus the full safety and grouped-evaluation gates |

### Frozen GRAPH-03 inventory and trigger

The first offline graph must retain every source-report variable: applicant
identity, visa class, sponsor, risk state, fee state, arrival date, page-to-case
assignment, page-type uncertainty, and source lifecycle
(`current`/`superseded`/`adversarial`). Its factor inventory is source authority,
case-ID binding, cross-page agreement, name grammar, field grammar, manual
corrections, strike-through/cancellation state, registration quality, OCR
confusion likelihood, and policy consistency. Its outputs are per-field
posterior, conflict probability, evidence-completeness probability, and a
diagnostic adjudication posterior.

Do not start while simpler provenance-aware selectors still have untested
headroom. The predeclared trigger census may count unresolved decision-critical
multi-source value conflicts, page-to-case/source-lifecycle mistakes,
field-selection errors, or measurable conflict/completeness uncertainty that a
single-field selector cannot represent. Start the first offline field-only graph
only when those retained outputs support at least `+0.10` recoverable points in
the relevant scored section. A calibration-only or action-consistency graph is a
separate future diagnostic identity and cannot be smuggled into this field
screen. The first graph cannot control an action. Any later action-control or
architectural proposal requires at least `+0.50` total points and every
safety/grouped-evaluation gate.

## H. Runtime allocation

| ID | Opportunity | Premise | Current status | Dependency | Disposition |
| --- | --- | --- | --- | --- | --- |
| RUN-01 | Reader hit/change/time telemetry | Value-of-information routing needs measured inputs | CONFIRMED | shared ROI experiments | PARK: hit/change/runtime telemetry implemented; score-gain numerator and reader-local timing remain unavailable pending paired outcomes |
| RUN-02 | Expected score gain per millisecond | Current routing is hand-authored and size-first | NO EXECUTABLE SCHEDULER CONTRACT | a surviving reader with paired out-of-fold gain and reader-local time | PARK; do not estimate value from a rejected reader or aggregate wall time |
| RUN-03 | Prioritize flags/adjudicator notes | Decision-critical fields can have greater marginal value, but priority must preserve evidence authority | HEURISTIC ONLY; NO FROZEN PRIORITY CONTRACT | RUN-02 inputs plus explicit source authority and wrong-denial/preservation gates | PARK; no priority treatment until the deterministic field ordering is frozen before outcomes |
| RUN-04 | Deprioritize already-corroborated fields | Re-reading well-supported values can add little information, but a skip can erase adverse or conflicting evidence | HEURISTIC ONLY; NO FROZEN SKIP CONTRACT | an exact evidence-completeness and provenance contract | PARK; never skip adverse, unknown, conflicting, note, identity-bound, or route-failure evidence |
| RUN-05 | Batch token bucket | Expensive readers need a hard aggregate budget | NO TOKEN-BUCKET IMPLEMENTATION OR TREATMENT | RUN-02 value/time inputs, a frozen deterministic bucket, a complete skip ledger, and batch stress | PARK; no scheduler claim until a paired end-to-end treatment closes |
| RUN-06 | Measured runtime reserve | Full completion matters more than consuming the whole limit | UNMEASURED | a fresh exact official-config 1,000-case completion/runtime receipt | PARK; predeclare a 15–20% reserve only after measurement, and do not claim a 20% reserve from the current root timing distribution |
| RUN-07 | Preserve watchdog/retry/atomic output | Existing reliability engineering is strong and should be reused | CONFIRMED | all runtime changes | PRESERVE |
| RUN-08 | Exact-byte OCR inference memo with retry continuation | OCR consumed 93.3% of the failed 1,000-case worker time; the frozen `MIB-000989` tail has 73 exact cross-process matches, zero product mismatches, 103.327849419 attempt-1 seconds, and 107.359998715 repeated attempt-2 seconds | DISABLED EVALUATOR-ONLY PROTOTYPE; LOCAL TAIL RESCUE AND 48-CASE IDENTITY LANES PASSED, DURABLE RECEIPT/RUNTIME LANE UNRUN | terminal standard-timeout treatment plus strict high-timeout attempt-1 cold reference; separate terminal equal-timeout 48-case off/on identity pair; official runtime gates | PARK: local rescue closes `MIB-000989` replay/recovery/cold semantics and local non-rescued outputs are byte-identical with zero retry hits, but terminal inputs are not committed, the standard-control failure is unreceipted/diagnostic-only, and no speed claim follows; runtime promotion stays false pending durable receipts and the official pair |
| RUN-09 | Same-view intra-case exact OCR deduplication | Exact engine inputs repeat inside one case and can be reused without collapsing their separate logical evidence contexts | BOUNDED `exact_v1` IMPLEMENTED; REAL 48-CASE SAME-STATE PAIR DIAGNOSTICALLY POSITIVE; FULL 1,000 UNRUN | terminal exact RUN-08 rescue/identity closure, then a fresh official-config 1,000-case run with immutable runtime/score receipts | GO for bounded combined verification, not SHIP: the real 48-case pair reduced physical calls 802→681 with 121 hits and byte-identical states, predictions, ledgers, and details; observer-inclusive wall delta is diagnostic only, and promotion remains false |
| RUN-10 | Native HQ suffix routing (`2 -> 1`) | The second HQ suffix costs at least 623.561 worker-seconds while preserving the full fast native ledger creates a strict-subset treatment | TELEMETRY + TREATMENT CONTRACT DESIGNED; UNIMPLEMENTED | publication-mandatory page/pass route ledger and two terminal distinct-state arms | GO for instrumentation, then a frozen `MIB_NATIVE_MAX_HQ=2 -> 1` experiment; PARK fast/page-type pruning because current OCR-derived routing cannot prove adverse-evidence preservation |
| RUN-11 | Inner OCR engine census | Top-level OCR rows hide 1–6 inner calls; Phase A closes exact physical input/output identity and duration, while Phase B (`RUN-11B`) separates preprocessing, detector, recognizer, batching, session, and cache cost | PHASE A IMPLEMENTED AT `f580782`; NONCANONICAL 48-CASE DIAGNOSTIC EXISTS; PHASE-B SPLIT FROZEN; ATTEMPTED MONOLITH REJECTED | terminal-bound phase-specific artifacts only when a surviving component lane needs its measured ceiling | PARK component-outcome claims; direct RUN-09/RUN-08 evidence means a passive full-1,000 census is no longer a prerequisite for exact reuse. Do not treat Phase A, either Phase-B half, or the failed monolith as complete RUN-11 |
| RUN-11A | Passive inner OCR call manifest | Exact physical call identity/output/duration can measure repetition but cannot decompose detector/recognizer components | IMPLEMENTED AT `f580782`; 48-CASE DIAGNOSTIC NONCANONICAL; FULL 1,000 CENSUS UNRUN | a terminal Phase-A manifest/parent receipt if a later decision still needs corpus-wide call identity | PARK as optional measurement, not the immediate critical path; observer wall deltas are overhead/noise rather than treatment gain, and Phase A cannot satisfy a component-timing dependency |
| RUN-11B-A | Engine component manifest | RUN-12/13/16/17 need preprocessing, detector, recognizer, batch, session, and per-line timing/hashes | SPLIT DESIGN COMPLETE AT `e6c7519`; ATTEMPTED MONOLITH FAILED HOSTILE REVIEW; NO COMMITTED IMPLEMENTATION | a new separately reviewed bounded implementation under the independent 700-line guard plus hostile terminal validator | PARK until separately implemented and terminally validated; the rejected prototype is not an integration candidate and every dependent treatment remains PARK |
| RUN-11B-B | Transform execution manifest | RUN-14 needs physical render/decode/despeckle/deskew keys and durations outside the engine observer | DESIGN COMPLETE AT `e6c7519`; IMPLEMENTATION UNRUN | separately scoped physical-key observer and hostile terminal validator | PARK until implemented and terminal; Artifact A cannot substitute for this evidence |
| RUN-11B | Complete component telemetry portfolio | A monolithic observer would create excessive attack surface and still blur independent publication gates | MONOLITHIC IMPLEMENTATION REJECTED BY COMPLEXITY GUARD; SPLIT PORTFOLIO UNRUN | terminal RUN-11B-A plus terminal RUN-11B-B | PARK until both artifacts exist; neither half alone is the complete RUN-11B contract |
| RUN-12 | Exact OCR data-plane adapter | Equal-size resize and grayscale-to-BGR allocation may touch the dominant inner loop; static preflight proves selected-view hashing is already winner-only and outside the inner inference loop | STATIC PREFLIGHT COMPLETE; COMPONENT CEILING UNMEASURED | RUN-11B component timing plus exact detector-tensor/output hashes; minimum 750 targeted worker-seconds per 1,000 | PARK until the component gate clears; promote only with byte-identical tensors, OCR, state, and provenance |
| RUN-13 | ONNX allocator and session hygiene | Memory-arena reuse and unused/duplicate sessions may reduce allocation and startup overhead | STATIC PREFLIGHT COMPLETE; 405.05 s GROSS CONSTRUCTION CEILING, EXACT REMOVABLE TIME UNMEASURED | RUN-11B construction/RSS events plus isolated configuration tests and 48-case recycling | PARK as supporting engineering; the full gross ceiling is only 1.32% of primary worker time and cannot close the target |
| RUN-14 | Immutable per-case render/decode cache | Static inspection confirms conditional repeated P0-B decode/despeckle/deskew paths; 150-DPI and 250-DPI renders are distinct | STATIC PREFLIGHT COMPLETE; measured masked/native render ceiling 292.365 s; P0-B overlap/time unmeasured | RUN-11B physical cache-key/timing telemetry and immutable array contract | PARK as supporting engineering and stability work; preserve exact physical-view and hidden-span boundaries |
| RUN-15 | Baseline HQ page/value routing | Any missing deny field currently reruns every scan page at HQ; the fresh trace attributes 2,281 primary HQ calls and 8,200.521 worker-seconds to this lane | SHADOW CONTRACT FROZEN; TREATMENT PARKED | a terminal `mib-baseline-hq-route-ledger-v1`, an independently defensible form-capability boundary, no more than three predeclared configurations, and terminal distinct-state arms | GO for passive label-free route accounting only; advance `singleton_fee_v1` to treatment only after the shadow ledger proves at least 1,500 conservative removable worker-seconds and 5% projected official wall reduction. Unknown, note, identity-conflicted, ambiguous, or route-failure pages retain the full path; require complete suppressed-evidence accounting, zero new CFA or wrong denial, no material worst-group regression, and a fresh official-config 1,000-case wall time at or below 4,800 seconds |
| RUN-16 | Adaptive detector resolution | Detector pixel count may dominate inner calls, but changed resolution can change evidence | THREE PRE-TRUTH UNIFORM ARMS FROZEN; EXECUTION UNRUN | RUN-11B detector timing and at least 1,500 removable detector worker-seconds per 1,000 or exact timeout rescue; frozen fast/HQ arms are 1280/2000, 1024/1600, and 768/1216 | PARK pending the component gate; no post-output cap substitution or fourth arm, and any changed output requires full distinct-state score/safety gates |
| RUN-17 | Recognition batch size | RapidOCR already batches six; 8/12 may reduce calls but can increase padded width and change recognition | STATIC PREFLIGHT COMPLETE; COMPONENT CEILING UNMEASURED | RUN-11B crop widths, padding, batch boundaries, recognizer timing, and per-line hashes; minimum 1,500 recognizer worker-seconds per 1,000 plus material 7–12-crop support | PARK; 6 is control and 8/12 are the only possible challengers, with same-state status only under exact per-line and full-state equality |
| RUN-18 | Native fast-page pruning | Native OCR is a large cost center, but OCR-derived page type can hide adverse, review, identity, or absence evidence and can change the later HQ suffix | UNSAFE FROM CURRENT EVIDENCE; UNRUN | a frozen route vocabulary and configuration plus a complete page/pass contribution ledger proving exact page-evidence and action-provenance preservation | PARK; unsafe from current evidence: unknown, conflicting, note-bearing, identity-conflicted, ambiguous, and route-failure pages retain the full path, and no page may be pruned unless its complete evidentiary contribution is preserved |

## I. Barcode and metadata firewall

| ID | Opportunity | Premise | Current status | Dependency | Disposition |
| --- | --- | --- | --- | --- | --- |
| BAR-01 | Strict typed barcode parser | Private packets may contain useful registry metadata | UNVERIFIED/LOW COVERAGE | direct corpus census | PARK |
| BAR-02 | Reject prose/imperatives | Barcode instructions are explicitly untrusted | CONFIRMED | BAR-01 | PRESERVE |
| BAR-03 | Case binding and lower authority | Schema-valid metadata still needs provenance | CONFIRMED | BAR-01 | PRESERVE |
| BAR-04 | Corroborate/conflict/neutral metadata only | Barcode cannot set policy or create approval | CONFIRMED | BAR-01 | PRESERVE |
| BAR-05 | Typed sponsor/registry barcode corroboration | A private packet could expose schema-valid sponsor or registry metadata even though the public 1,000-packet census decoded no useful payload | UNVERIFIED/PRIVATE-TEST CONDITIONAL | BAR-01 strict schema, case binding, lower-than-visible authority, matching visible evidence, and adversarial instruction rejection | PARK; corroborate or surface conflict only, never fill clearance, set policy, or create approval |

## J. Narrative and code-review credibility

| ID | Opportunity | Premise | Current status | Dependency | Disposition |
| --- | --- | --- | --- | --- | --- |
| MEM-01 | Visible-evidence/uncertainty thesis | Better describes the real task than generic OCR | CONFIRMED | final shipped architecture | OPEN |
| MEM-02 | Paint-order and two-physical-view narrative | Strong differentiator if final artifact proves it | CONFIRMED | exact final artifact | OPEN |
| MEM-03 | Direction-asymmetric recovery narrative | Strongest existing architectural insight | CONFIRMED | final reader set | OPEN |
| MEM-04 | One strongest negative result | Demonstrates judgment without development-log sprawl | CONFIRMED | source experiment receipt | OPEN |
| MEM-05 | Narrow injection claim | No instruction follower removes prompt-following, not all evidence poisoning | CONFIRMED | none | OPEN |
| MEM-06 | Conditional score-optimal wording | Current runtime is not score-optimal | CONFIRMED | ARB disposition | OPEN |
| MEM-07 | Audited-visible-channels failure wording | "Irreducible" overstates absence proof | CONFIRMED | none | OPEN |
| MEM-08 | Per-field confidence | Potentially useful future output/diagnostic | UNVERIFIED | grouped field posteriors | PARK |

## K. Explicit no-go register

| ID | Direction | Status |
| --- | --- | --- |
| NG-01 | Hidden answer-key or hidden-field transcription | NO-GO |
| NG-02 | Case-ID, filename, PDF-hash, or page-signature label lookup | NO-GO |
| NG-03 | Missing-fee or missing-risk approval priors | NO-GO |
| NG-04 | Mode imputation for destroyed fields | NO-GO |
| NG-05 | Generic field-to-policy machine learning | NO-GO |
| NG-06 | Generic red-stamp outcome detector | NO-GO |
| NG-07 | Generative super-resolution/invented evidence | NO-GO |
| NG-08 | Full-page high-DPI OCR on every page | NO-GO |
| NG-09 | Large neural document-model rewrite | NO-GO |
| NG-10 | Manual validation-case corrections or pseudo-labeling | NO-GO |
| NG-11 | Whole-string majority vote without alignment/grammar | NO-GO |
| NG-12 | Forced low-quality registration | NO-GO |
| NG-13 | Barcode instructions influencing fields, policy, or approval | NO-GO |
| NG-14 | Calibration on predictions used to design its buckets | NO-GO |
| NG-15 | Treating phrase absence as approval evidence | NO-GO |
| NG-16 | Untracked, stitched, partial, or placeholder-filled scored runs | NO-GO |
| NG-17 | Wholesale architecture rewrite before simpler lanes plateau | NO-GO |
| NG-18 | Claiming private-test superiority as a confirmed fact | NO-GO |
| NG-19 | Summing overlapping speculative point estimates | NO-GO |
| NG-20 | Promoting a change without an immutable receipt | NO-GO |

## Orchestration order

1. `CTRL/EVAL`: repair and freeze the experiment contract.
2. `SAFE`: classify current semantic contradictions and close runtime-surface
   hazards.
3. `POL`: run cheap visible-policy residual experiments.
4. `OCR/REG/CTC`: use one shared ROI laboratory and attribution grid.
5. `ARB/RLA`: act only on grouped, cross-fitted evidence after extraction
   stabilizes.
6. `RUN`: allocate the surviving readers under a measured budget.
7. `GRAPH/BAR`: attempt only if simpler lanes plateau and time/support remain.

## Closing addendum (2026-07-31)

Final pre-submission measurements taken after this register's date. Each is a
measured decline, not an open opportunity; none changed the shipped code or
predictions.

- **Hedge-resolution resolver (rival-style EV forest), measured on our 258
  eligible hedges:** in-sample +4.83 total at 13 catastrophic false approvals;
  honest 5-fold out-of-fold replication of the same architecture across three
  fold seeds yields +1.35 to +2.75 total at 3–25 new CFAs per 1,000 depending
  on guard. No CFA-clean operating point exists: the approve-only
  conf ≥ 0.695 guard that shows zero false approvals in-sample mints 3–8 out
  of sample. Declined.
- **Confidence-threshold hedge conversion:** +2.48 train at 34 CFAs. Declined.
- **NR & conf < 0.5 → APPROVED remap:** +0.075 net, CFA 1 → 43. Declined.
- **Fee dark head:** +0.946, CFA 1 → 3. Ships disabled.
- **Flags head (never built; reconstructed ceiling):** +0.65 to +0.77,
  CFA 1 → 11. Not built.
- **Calibration transforms:** all negative under cross-validation; the fitted
  temperature is the identity, and oracle isotonic is worth +0.049. Unchanged.
- **POL-12 dual fee-clearance unlock:** generator-impossible — 0/1,000 train
  packets carry two fee-bearing surfaces, and an exhaustive 4,096-conjunction
  zero-D search is empty. The POL-12 row above is superseded: CLOSED, not PARK.
- **Deny-flag residual:** information-bounded — of 35 denied-hedge flag cases,
  14 have no scan surface and 21 were attempted and failed the evidence gate;
  truth-word template scores (0.41–0.61) are indistinguishable from truth-none
  controls (0.38–0.63, n=21 vs 30).
- **Hedge residual 40-case audit:** 37 information-absent, 3 policy-correct
  declines on untrusted surfaces (SAMPLE DENIAL / ARCHIVE / hidden text),
  0 clean misreads.
- **Fee residual mechanism:** absent waiver evidence — 86/123 fee misses are
  truth `waived` with the waiver-code page absent (evidence pools empty in
  96/123) — not "unreadable unknown".
