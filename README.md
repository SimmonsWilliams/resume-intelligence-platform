# Resume Intelligence Platform

A Streamlit decision-support application for resume intelligence. It preserves an existing report-driven recruitment dashboard and adds synthetic Demo Mode and session-only DOCX resume analysis.

## Features

- Existing Local Reports mode for repository-generated batch reports
- Public-safe, fictional Demo Mode
- DOCX-only Resume Analysis mode with in-memory extraction
- V2 ontology-based skill and evidence extraction
- Data-quality validation
- Skill, education, experience, and project matching
- Existing scoring engine with component coverage and manual-review reasons
- Sanitized CSV and JSON exports
- Mandatory session-state `Clear Analysis` control
- Six dashboard pages: Executive Dashboard, Candidate Ranking, Candidate Profile, Analytics, Data Quality, and Reports

## Privacy and limitations

- Resume uploads are processed in memory and are not written to the repository or private candidate folders.
- Uploaded text, profiles, and results are retained only temporarily in Streamlit session state.
- `Clear Analysis` removes application references from session state. It does not guarantee secure deletion from server process memory, caches, backups, or runtime storage.
- Use synthetic or permitted documents only. Do not upload sensitive or confidential resumes.
- Scores are decision-support indicators only. Human verification is mandatory; no score implies automatic selection or rejection.
- Demo Mode defaults to synthetic fictional data and must not be used with private report folders.

## Requirements

Use the existing virtual environment when available:

```bash
cd ~/Development/Resume-Checker-Project
source .venv/bin/activate
python -m pip check
python -m pip install -r requirements.txt
```

## Run locally

```bash
cd ~/Development/Resume-Checker-Project
.venv/bin/python -m streamlit run app.py --server.address=127.0.0.1 --server.port=8501
```

Open `http://127.0.0.1:8501`. The public/demo startup defaults to Demo Mode.

## Test locally

```bash
cd ~/Development/Resume-Checker-Project
.venv/bin/python -m compileall -q app.py resume_upload.py resume_parser.py resume_analyzer_v2.py resume_job_matcher.py data_quality_validator.py project_matcher.py scoring_engine.py job_description_analyzer.py tests
.venv/bin/python -m pytest -q
```

Tests use synthetic DOCX files and in-memory objects. They do not read private candidate folders or real resumes.

## Runtime modes

### Existing Local Reports

Loads existing repository report and profile data only. Missing or malformed reports produce visible unavailable states and do not trigger Demo Mode.

### Demo Mode

Uses fictional in-memory demonstration records. It does not load private folders or report records.

### Resume Analysis

Accepts one `.docx` file up to 5 MB, extracts text in memory, runs the V2 analyzer, validates quality, performs matching and scoring, and produces sanitized downloads. PDF and other formats are rejected.

## Screenshots

Capture screenshots with only synthetic Demo Mode or synthetic test documents. Do not include real candidate names, organizations, filenames, addresses, emails, or phone numbers.

## Project status

Implemented and automated-test verified. Deployment is complete only after a public Streamlit URL passes a live smoke test.

## Streamlit Community Cloud deployment

1. Sign in to Streamlit Community Cloud with GitHub.
2. Create an app from `SimmonsWilliams/resume-intelligence-platform`.
3. Select branch `main` and main file `app.py`.
4. Deploy the app. No secrets or environment variables are required.
5. Open **Manage app > Settings > Sharing**.
6. Set **Who can view this app** to **This app is public and searchable**.
7. Verify the public URL without signing in. If the URL redirects to `/-/auth/app`, the app sharing setting is still private or GitHub authorization is incomplete.

The repository must remain public-safe and must not contain private resumes or report directories.
