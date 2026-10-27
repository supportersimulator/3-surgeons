# GainsGate critical-findings fail-closed — GitHub Actions evidence

**Source:** GitHub Actions runs on this PR's actual commits, not simulated or copied output. All runs used the repository CI workflow; status is **RED** for baseline/unrelated problems described below. No production runtime tests or secrets were used.

## Regression-first commits and outcomes

| Git commit | GitHub Actions run | Python 3.12 pytest results | Meaning |
| --- | --- | --- | --- |
| [`8351d035`](https://github.com/supportersimulator/3-surgeons/commit/8351d035c916b206d9f5299cdc5e124a7a788f17) — tests only, original gate | [40444062976](https://github.com/supportersimulator/3-surgeons/actions/runs/40444062976) | **5 failed, 1,734 passed, 1 skipped, 10 deselected** | All 5 new negative cases fail on original fail-open behavior; 2 positive new controls pass. |
| [`0172a3de`](https://github.com/supportersimulator/3-surgeons/commit/0172a3de25236b892d5dba528bc3c034551a9260) — code fix | [40444143470](https://github.com/supportersimulator/3-surgeons/actions/runs/40444143470) | **1 failed, 1,738 passed, 1 skipped, 10 deselected** | All 7 new cases pass; an old positive test incorrectly treated missing count as zero. |
| [`5c580486`](https://github.com/supportersimulator/3-surgeons/commit/5c580486dae6fd933e4a16852011e3b7c73e9fb6) — old positive control explicitly sets count zero | [40444300708](https://github.com/supportersimulator/3-surgeons/actions/runs/40444300708) | **1,739 passed, 1 skipped, 10 deselected, 0 failed** | All 7 new cases pass and the existing test is meaningful again. |

Red-before source verdicts (exact behavior observed in 3.12 run):
- Invalid `NaN`, empty and `1.5` counters: `CheckResult(... passed=True, message="Critical findings check error (defaulting pass): ...", critical=True)`.
- Counter absent: `CheckResult(... passed=True, message="No unresolved critical findings", critical=True)`.
- Backend read exception: `CheckResult(... passed=True, message="Critical findings check error (defaulting pass): synthetic state read failure", critical=True)`.

Final implementation blocks **all those cases**, reports the required key and a `Recovery:` instruction, and logs the failure at ERROR level. Counter `0` passes, counter `3` fails. The test explicitly enables `critical_findings` in `gains_gate_checks`; it is **off by default** in current configuration. No writer for an authoritative count is introduced here.

## Why the entire CI workflow remains RED

- Python 3.12 **unit-test step passed all selected tests**, but its subsequent **launcher smoke test** failed. The full workflow is therefore not green.
- Python 3.10: the same **10 `tests/test_consensus_json.py` cases** failed with `AttributeError: <function main ...> does not have the attribute 'LLMProvider'` both on the original test-only commit (15 total failures = 5 new + 10 existing) and after the patch (10 total failures). This is not caused or resolved by GainsGate.
- Python 3.9 matrix jobs fail in `actions/setup-python@v5` before tests.
- Existing broad ruff/lint debt (1,465 findings reported in CI) is not in scope. The workflow's red result is **not** to be bypassed; the owning CI/launcher fixes need their own reviewed PRs.

## Merge/wiring boundaries

- **Draft only; no merge authorization.** No live service, credential or runtime configuration was changed.
- Merging [CorrigibilityGate draft PR #4](https://github.com/supportersimulator/3-surgeons/pull/4) may require integration/rebase because both touch `three_surgeons/core/gates.py`; preserve each PR's independent negative tests.
- The gate's **unknown configured check** (non-critical fail-open in `GainsGate.run`), the **critical_findings check being disabled by default**, and **absence of an authoritative counter writer** remain separate risks. Do not represent this PR as enabling complete critical-finding governance.
- Future acceptance for runtime activation: authoritative count derivation, confirmed reader/writer, failure and recovery tests, and full CI/launcher health. This PR only corrects one explicit failed-read/unknown-count interpretation.
