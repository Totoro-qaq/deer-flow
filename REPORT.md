# Two attribution-control candidates

These cases help distinguish final-artifact quality, measurement behavior and evaluator evidence access. They are candidates for misattribution controls. They do not test an RSI admission policy, demonstrate an improvement in agent capability, or quantify the benefit of human intervention. The source analyses were completed on October 22 and 23, 2026; this public summary was prepared on October 24.

## A. Correcting a meeting-note measurement

The unit is a saved final output set for 60 meetings. There are eight sets: four English and four Chinese, with 480 meeting-note outputs in total. They reuse two source-language corpora of 60 meetings each. These are not eight independent random benchmark samples.

The historical scorer reproduces all eight recorded results on the same saved artifacts: four sets pass 5/5 checks, and four fail at 4/5. The offline scorer `minutes-strict-v1` returns 5/5 for all eight, with zero parser uncertainties. No agent was rerun and no deliverable was edited or regenerated. Goal verdicts and evaluator explanations are excluded from this scoring.

The four changed labels come from legacy index-parser false negatives. The legacy parser can select a date-bearing introduction or path instead of a meeting-table row, then infer an action count from an unrelated number. In affected sets it reports 57/60 or 58/60 correct index counts. The corrected parser finds all 60 required meeting rows and all 60 exact per-meeting counts in each set.

The new scorer also strengthens the registered checks: every expected nonempty file; source topic, full date, all attendees, decision token and exact action count; each action's description, owner and due date together; real decision/action sections; exactly one identifiable index row per meeting; and exact counts in a labelled count column. It removes the legacy N-1 tolerance and first-match behavior. Seventeen local standard-library tests are reported as passing. Single-defect controls show legacy passes but strict fails one wrong count, one missing attendee and a duplicate index row. Those controls distinguish stricter rules from the parser corrections that explain the observed four label changes.

**Scope matters:** 8/8 means the registered facts and structure pass. It does not validate every discussion sentence, every decision clause, optional aggregate prose or supplementary trackers. In Run6, an optional prose action total says **175**, while the source total is **177**. Its 60 required per-meeting counts are correct; the prose error remains and is not validated by the score. English source actions total 180. These final-output regrades also say nothing about the timing or correctness of earlier completion claims. Unsupported layouts or paraphrases may need manual review.

The [CSV](minutes-regrade.csv) has eight anonymized rows. `c1` through `c5` follow the check order in [case-data.json](case-data.json). Recorded check flags are reconstructed from the recorded failing-check list and checked against the recorded score; the legacy replay matches every recorded score. Legacy and strict checks share the five categories, with the stricter requirements described above. No original unit identifiers or paths are published.

## B. Evidence removed before the evaluator

A replay of the unchanged native formatter uses retained first-turn state at source commit `505c33c793389451f2ce7183bdbd4f3465f22f66`. The lead agent received the same 10,375-character user message in both observed cases, including Document 5. Character counts below apply to conversation evidence; they exclude the separately prepended objective and evaluator instructions.

| Retained first-turn case | Before cap | After cap | Unused 12,000-character budget | Document 5 retained |
| --- | ---: | ---: | ---: | --- |
| Observed A | 11,953 | 11,953 | 47 | yes |
| Observed B | 12,127 | 3,767 | 8,233 | no |

The formatter packs whole message lines. When the latest user line is omitted, a fallback keeps only 1,994 original user characters, followed by a truncation marker. Document 5 begins at source offset 3,694 and is lost. The historical evaluator then reports missing evidence for Document 5; the lead agent had received it. The reconstruction uses the disabled-by-default redaction configuration, so redaction does not explain this loss.

The observed answers differ, and their different historical verdicts do not establish a causal effect of truncation on verdict quality. A separate boundary control holds the user message and whitespace-normalized answer fixed. One additional internal space moves input evidence from **12,000 to 12,001** characters; retained evidence falls from **12,000 to 3,641**, dropping Document 5 and leaving 8,359 characters unused. This isolates a discontinuity in evidence allocation.

These are zero-provider formatter reconstructions, not new model responses or historical wire captures. They read no future turns or reference answers and generate no counterfactual verdict. No fuller-evidence rerun was performed; improved adjudication after restoring evidence has not been demonstrated.

## Provenance and limits

[Case data](case-data.json) preserves denominators, eight per-set results, boundary measurements, the frozen source version and selected SHA256 hashes. The original regrade report's hash commits to its complete 617-input manifest, retained locally. All 617 local inputs were rechecked against that manifest while preparing this package, with zero missing files or hash mismatches. Raw prompts, responses, meeting text, private identifiers, source code and experiment/drawing scripts are excluded.

The supported findings are a measurement correction on unchanged artifacts and a reproducible evidence-allocation boundary. These are useful attribution-control candidates. Generalization, RSI admission decisions, restored-evidence verdicts and human-intervention benefit remain untested.
