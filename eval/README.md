# Multi-model Start Prompt Benchmark

Benchmark-02 compares three arms (`bare`, `v4`, `v5-single`) independently on four
target models. It produces blinded response artifacts, majority-vote criterion
scores, conservative per-model statistics, and hash-verified frozen snapshots.

## Files

- `config.yaml` — models, three arms, profiles, decoding, and judge configuration
- `prompts/v4.md` — current Start Prompt
- `prompts/v5.md` — generated, self-contained V5 distribution build
- `build_v5.py` — deterministically rebuild/check the single-file V5 from top-level
  `core/` and `modules/`
- `run.py` — target-model generation phase; never judges
- `judge.py` — condition/model-blind scoring phase
- `report.py` — per-model/category Markdown report
- `freeze.py` — snapshot and verify prompts, cases, contract, config, runner, and model IDs
- `SCORING_CONTRACT.md` — rules that govern a frozen decision run

## 1. Prepare Python

Python 3.9+ and PyYAML are required. The HTTP clients use the standard library, so
provider SDKs are not required.

```bash
cd /Users/hzuo/Documents/code/AI-Operations
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r eval/requirements.txt
```

## 2. Build the copy-ready V5

```bash
python eval/build_v5.py
python eval/build_v5.py --check
```

The resulting `eval/prompts/v5.md` is the exact one-file Prompt used by arm C and can
be pasted into an AI agent's Start Prompt/System Prompt field.

## 3. Configure connections

Copy values from `env.example` into your shell or a secret manager. Do not put API
keys in `config.yaml`, run artifacts, or freeze directories.

Each `*_BASE_URL` must include the API version prefix expected before
`/chat/completions`, commonly `/v1`. Each `*_MODEL_ID` must be the exact provider ID,
not a display name inferred from this repository.

The four target entries default to the OpenAI-compatible Chat Completions adapter.
Available adapters are:

- `openai_chat`
- `anthropic_messages`

Provider-specific request fields can be set in a model's `extra_body`. If a model
rejects temperature, set `supports_temperature: false`. If its token field differs,
set `max_tokens_field`.

## 4. Inspect the pilot without spending API calls

```bash
python eval/run.py --profile pilot --dry-run
```

The default pilot is:

```text
4 models × 3 arms × 4 cases × 1 run = 48 generation calls
```

The pilot uses one judge vote per LLM criterion (36 judge calls across all four
models). Development and holdout use three-vote majority judging.

Run a subset while validating one provider:

```bash
python eval/run.py --profile pilot --models glm-4.7 --dry-run
python eval/run.py --profile pilot --models glm-4.7
```

The live command prints a `run_id`. Runs are stored under `eval/out/<run_id>/` and
can be resumed by passing the same `--run-id`. Outputs are never reused across a
different model, Prompt hash, case hash, or decoding configuration.

## 5. Judge and report a pilot

```bash
python eval/judge.py --run-dir eval/out/<run-id> --dry-run
python eval/judge.py --run-dir eval/out/<run-id>
python eval/report.py --run-dir eval/out/<run-id>
```

Use a judge that is not one of the target models when possible. The report is written
to `eval/out/<run-id>/report.md`.

Pilot results are for API/schema/judge calibration only. They cannot decide adoption.

## 6. Freeze a decision benchmark

Set exact target and judge base URLs/model IDs first. API keys are not needed to
create the freeze and are never copied.

```bash
python eval/freeze.py --name benchmark-02-v4-v5
python eval/freeze.py --verify <freeze-id>
```

The freeze ID includes the combined content hash. A freeze locks:

- config and decoding settings
- cases and attachments
- V4 and single-file V5
- scoring contract
- runner/judge/report code
- exact model IDs, endpoint hashes, and judge fingerprint

Changing any frozen input requires a new freeze.

## 7. Development and holdout runs

```bash
python eval/run.py --profile development --freeze <freeze-id>
python eval/judge.py --run-dir eval/out/<development-run-id>
python eval/report.py --run-dir eval/out/<development-run-id>
```

Complete judge calibration and the required human audit before holdout:

```bash
python eval/run.py --profile holdout --freeze <same-freeze-id>
python eval/judge.py --run-dir eval/out/<holdout-run-id>
python eval/report.py --run-dir eval/out/<holdout-run-id>
```

Development and holdout are always separate runs and reports. Never merge their
manifests or use holdout results to edit prompts or criteria.

## Security and reproducibility

- Only environment-variable names are stored in config.
- API keys are excluded from run metadata, errors, and freezes.
- Base URLs are recorded only as SHA-256 fingerprints in persistent metadata.
- Full and holdout profiles refuse to run without a verified freeze.
- A frozen run refuses changed runner code, model IDs, endpoints, or judge identity.
