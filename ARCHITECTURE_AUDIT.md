# Architecture Audit — Resume Intelligence Platform

**Audit scope:** Stage 1 only. This document describes the repository as inspected. No application code or dependencies were changed.

## 1. Executive Summary

The project is a pipeline of standalone Python scripts plus a Streamlit dashboard:

`DOCX extraction -> resume analysis -> candidate profiles -> quality validation -> project matching -> scoring/ranking -> Streamlit reports`

The repository already contains substantial resume analysis and explainable scoring logic. The safest integration direction is to reuse `resume_analyzer_v2.py`, `resume_job_matcher.py`, `data_quality_validator.py`, `project_matcher.py`, and `scoring_engine.py`, rather than rewrite business logic or merge the alternate implementations.

The existing dashboard (`app.py`) is report-driven and does not import the analysis modules. It is mostly defensive around missing CSV/JSON reports, but it expects real scoring data for several views and has no synthetic fallback or upload workflow.

## 2. Inspected Modules

| File | Responsibility | Current status |
|---|---|---|
| `app.py` | Streamlit recruitment dashboard with executive, ranking, profile, analytics, quality, and report pages | Primary dashboard entry point; reads local reports and `analyzed_data/` only |
| `resume_parser.py` | Extracts paragraphs and tables from DOCX files and writes extracted JSON/CSV | Primary DOCX parser; currently file-path-centric and creates local output directories at import |
| `resume_analyzer.py` | Basic section parsing and fixed SKILL keyword list | Legacy/basic implementation |
| `resume_analyzer_v2.py` | Ontology-based section and skill extraction with evidence/confidence metadata | Recommended primary analyzer |
| `resume_job_matcher.py` | Skill, education, and employment experience matching | Recommended primary matcher; used by `scoring_engine.py` |
| `resume_job_matcher_fixed.py` | Alternative/fixed copy of the matcher | Duplicate/alternative implementation; not imported by the scoring engine |
| `resume_job_matcher_backup.py` | Backup matcher implementation | Local backup artifact; not active |
| `data_quality_validator.py` | Candidate field/type/duplicate/date validation | Reusable validation implementation |
| `job_description_analyzer.py` | Loads and prints job description fields | Utility/CLI module, not a persisted report pipeline |
| `project_matcher.py` | Infers project grouping and matches project evidence to job terms | Reusable project matching implementation |
| `scoring_engine.py` | Component scoring, coverage, manual-review notes, ranking, and CSV/JSON reports | Primary scoring/ranking implementation |
| `skill_ontology.json` | Runtime skill ontology | Loaded by the V2 analyzer |
| `job_descriptions/*.json` | Sample job descriptions | Safe sample configuration data; no private candidate information in inspected samples |
| `requirements.txt` | Pinned runtime dependencies | Includes Streamlit, Pandas, Plotly, python-docx, and supporting packages |
| `README.md` | Basic setup/run documentation | Needs deployment/privacy/demo documentation updates |
| `.gitignore` | Exclusion rules for private folders, backups, secrets, resumes, and virtual environments | Mostly effective, but review should ensure staged/committed private folders remain excluded and never tracked |

## 3. Key Function Signatures and Data Formats

### `resume_parser.py`

- `extract_text(file_path)` -> `str`
  - Expects a DOCX path accepted by `python-docx.Document`.
  - Returns paragraphs and table cells joined with newline characters.
  - Table rows are rendered as `" | "`-joined strings.
  - Raises parser exceptions for malformed/unreadable documents.
- `process_resumes()` -> `None`
  - Recursively loads `Resume docs/*.docx`.
  - Writes `extracted_data/all_resumes.json`, per-candidate JSON, and `reports/extraction_errors.csv`.

Extracted candidate shape:

```json
{
  "candidate_id": "CAND-001",
  "source_file": "filename.docx",
  "full_text": "...",
  "character_count": 1234,
  "extraction_status": "SUCCESS"
}
```

An in-memory file-like integration can be added by allowing `extract_text()` to accept a file object supported by `python-docx.Document`, but the existing signature and path behavior should not be silently changed.

### `resume_analyzer_v2.py`

- `normalize_text(value)` -> `str`
- `load_ontology()` -> `dict[str, str]` mapping canonical skill name to category
- `get_sections(text)` -> `dict[str, list[str]]`
- `compile_skill_patterns(ontology)` -> `list[(str, str, re.Pattern)]`
- `extract_skill_evidence(sections, patterns)` -> `list[dict]`
- `discover_unknown_candidates(sections, known_patterns)` -> `list[dict]`
- `analyze_candidate(candidate, patterns)` -> `dict`

The profile output includes:

- `candidate_id`
- `source_file`
- `skills`
- `skill_evidence`, with section, evidence line, evidence type, confidence, and verification flag
- `potential_skill_candidates`
- `education`, `experience`, `experience_evidence`, `projects`, `certifications`
- `professional_summary`, `awards`, `section_counts`
- `extraction_status`, `verification_required`, and `analyzer_version`

`analyze_candidate()` returns an analyzed profile and does not persist files. This is suitable for a Streamlit upload path. It tolerates missing `full_text` as an empty string.

### `resume_analyzer.py`

- `normalize_heading(text)` -> `str`
- `get_sections(text)` -> `dict[str, list[str]]`
- `find_skills(text)` -> `list[str]`
- `find_experience_evidence(lines)` -> `list[str]`
- `analyze_candidate(candidate)` -> `dict`

It contains a fixed skill list and an older heading algorithm. It is not ontology/evidence aware and should remain a compatibility/legacy implementation unless a separate requirement exists.

### `resume_job_matcher.py`

- `normalize_skill(skill)` -> `str`
- `match_skills(candidate_skills, job)` -> `dict`
  - Candidate skills and job skill lists are expected to be lists or sequences of strings.
  - Returns matched/missing lists for required and preferred skills.
- `normalize_education(text)` -> `str`
- `match_education(candidate_education, job)` -> `dict`
  - Education can be a string or list.
  - Job `education` can be a list, string, or absent/malformed.
  - Returns `status`, `matched`, `missing`, `manual_review`, and `evidence`.
- `extract_employment_entries(candidate, current_date=None)` -> `(list[dict], bool)`
- `match_experience(candidate, job, current_date=None)` -> `dict`

The experience result includes total, employment, internship, and relevant months/years, public employment entries, requirement matches/misses, status, and manual-review messages. Supported date ranges include years or month-year ranges ending in a year, month-year, `present`, `current`, or `now`. Internships are tracked separately and do not determine the normal employment requirement alone.

### `resume_job_matcher_fixed.py`

Exports the same major matcher function names and closely overlapping behavior, but is not used by `scoring_engine.py`. It omits several fresher/manual-review fixes and maximum-bound handling present in `resume_job_matcher.py`. It should be designated legacy/duplicate, not enhanced independently.

### `data_quality_validator.py`

- `is_empty(value)` -> `bool`
- `find_duplicates(values)` -> `list[str]`
- `validate_candidate(candidate)` -> `dict`

Expected profile fields include `candidate_id`, `source_file`, `skills`, `education`, `experience`, `projects`, `certifications`, `professional_summary`, and `awards`. It validates types and emptiness and returns:

- `validation_status`: `VALID`, `REVIEW_REQUIRED`, or `INVALID`
- `issue_count`, `warning_count`
- `issues`, `warnings`, and `missing_optional_sections`

The module also has a later second validation implementation in the same file. The duplicate local code should be reconciled or removed before further integrations, but `validate_candidate()` is the named primary function.

### `project_matcher.py`

- `load_candidates()` -> `list[dict]`
- `load_jobs()` -> `list[dict]`
- `clean_project_line(value)` -> `str`
- `starts_like_description(text)` -> `bool`
- `group_projects(project_lines)` -> `(list[dict], list[dict])`
- `normalize(text)` -> `str`
- `find_phrase_matches(projects, phrases)` -> `list[dict]`
- `match_candidate_projects(candidate, job)` -> `dict`

The project result includes grouped projects, project count, status, matched/missing required skills, preferred skills, software tools, and minimum-project evaluation. Grouping is explicitly heuristic and carries a grouping review note.

### `scoring_engine.py`

- `load_json(path)` -> JSON value
- `load_candidates()` -> `list[dict]`
- `load_jobs()` -> `list[dict]`
- `load_optional_report(path, issues, expected_type)` -> report or `None`
- `_new_component(...)` -> `dict`
- `score_skill_component(...)`, `score_education(...)`, `score_experience(...)`, `score_projects(...)` -> component dictionaries
- `evaluate_candidate_job(candidate, job, project_result, quality_result)` -> `dict`
- `rank_records(records, jobs)` -> `list[dict]`
- `run()` -> `None`; CLI entry point
- `main()` -> exit code

Weights are:

- Required skills: 25 points
- Preferred skills: 10 points
- Education: 15 points
- Experience: 25 points
- Projects: 25 points

Normalization is earned points divided by weighted capacity with evidence, multiplied by 100. Missing/unusable components are excluded from capacity rather than assigned a silent zero. Component points are on 0–weight ranges and overall score is reported as 0–100 when capacity exists. `overall_score` can be `None` when no weighted evidence can be scored. Evaluation can be `EVALUATED`, `PARTIAL_DATA`, or `MANUAL_REVIEW`.

### `job_description_analyzer.py`

- `load_job_description(file_path)` -> `dict`
- `analyze_job(job_data)` -> `None`/print-only

## 4. Current Data Flow

### Batch pipeline

1. `resume_parser.py` scans `Resume docs/*.docx` and writes extracted records to `extracted_data/`.
2. `resume_analyzer.py` or `resume_analyzer_v2.py` reads an extracted list and produces profile JSON.
3. The V2 path writes `analyzed_data_v2/all_profiles.json`; the basic path scripts output `analyzed_data/` and may use a separate profile schema.
4. `data_quality_validator.py` validates batch profiles and writes quality reports.
5. `project_matcher.py` reads candidates and jobs and writes project-match JSON/CSV.
6. `scoring_engine.py` loads `analyzed_data/all_profiles.json`, jobs, and optional project/quality reports.
7. The scoring engine writes final scoring and ranking JSON/CSV reports.
8. `app.py` loads CSV and JSON reports and displays dashboard pages.

### Stage 4 dashboard data flow

- `app.py` exposes exactly three runtime modes.
- Demo Mode is the public-safe default and uses only fictional in-memory records.
- Existing Local Reports reads only repository reports and profile data.
- Resume Analysis accepts DOCX bytes, validates and extracts them in memory, and passes them through `resume_upload.py`.
- `resume_upload.py` reuses V2 analysis, quality validation, matchers, project matching, and scoring; it does not persist uploads.
- CSV and JSON downloads contain only generic processing IDs and sanitized summaries.
- `Clear Analysis` removes application references from Streamlit session state but does not claim secure memory erasure.

### Actual dashboard data flow

- `app.py` computes absolute project-relative paths.
- It loads the five named CSV report files.
- It loads `analyzed_data/all_profiles.json` and optional project/final-scoring JSON reports.
- Missing CSV/JSON files return empty frames or `None` with warning/error messages.
- Several views require at least a scoring CSV and `job_id`; some data-quality/profile views remain usable when reports are absent.
- The app provides Demo, Existing Local Reports, and Resume Analysis runtime modes.
- Resume Analysis uses `st.file_uploader`, in-memory DOCX extraction, V2 analysis, matching, scoring, sanitized exports, and session-state clearing.

## 5. Duplicate and Conflicting Implementations

1. **Resume analyzers:** `resume_analyzer.py` is basic/fixed; `resume_analyzer_v2.py` is ontology/evidence-aware and more complete. The V2 analyzer is the primary implementation for integration.
2. **Resume matchers:** `resume_job_matcher_fixed.py` duplicates much of `resume_job_matcher.py`. The regular matcher is newer and has fresher handling, internship separation, date-range fixes, and maximum-year matching. `scoring_engine.py` explicitly imports the regular matcher; it is primary.
3. **Backups:** `*_backup.py`, `*.backup`, `app_backup.py`, and `resume_job_matcher_backup.py` are inactive alternatives. They should not be imported or used.
4. **Profile directories:** `analyzed_data/` and `analyzed_data_v2/` contain separate batch outputs. The dashboard uses `analyzed_data/`; the V2 analyzer writes `analyzed_data_v2/`. The integration must either standardize one profile directory or pass profiles in memory from a shared workflow.
5. **Validation duplication:** `data_quality_validator.py` contains a named `validate_candidate()` implementation followed by another candidate-validation block before `validate_all_candidates()`. The later block may be unreachable unless attached to a function; this ambiguity should be resolved in Stage 5/6.
6. **Report naming mismatch:** the V2 analyzer writes `analysis_report_v2.csv`, while `app.py`'s report map expects `analysis_report.csv`. The dashboard currently will not receive V2 analysis reports without explicit normalization.
7. **Job/matcher schema differences:** not all matcher fields are required consistently. `education` and `experience` may be absent or malformed; skill lists may be absent; project minimum values can be absent. Existing functions generally handle many missing values, but integration should preserve and surface review states rather than assume data exists.

## 6. Recommended Primary Implementations

- **DOCX extraction:** `resume_parser.extract_text()`; add a file-like interface in a separate upload adapter, preserving the existing path interface.
- **Resume analysis:** `resume_analyzer_v2.analyze_candidate()` plus `load_ontology()` and `compile_skill_patterns()`.
- **Skill matching:** `resume_job_matcher.match_skills()`.
- **Education matching:** `resume_job_matcher.match_education()`.
- **Experience matching:** `resume_job_matcher.match_experience()`.
- **Project relevance:** `project_matcher.match_candidate_projects()`.
- **Data quality:** `data_quality_validator.validate_candidate()`.
- **Scoring:** `scoring_engine.evaluate_candidate_job()`.
- **Dashboard:** minimal changes to `app.py`, plus a small modular helper/module for upload/processing orchestration rather than moving business logic into Streamlit UI code.

Do not modify or replace `resume_job_matcher_fixed.py` in the integration unless a specific bug is found and approved. Do not import `resume_analyzer.py` for the new upload path if V2 evidence support is required.

## 7. Integration Plan (To Be Approved After Audit)

1. Add synthetic demo data that is clearly fictional, and a demo fallback that activates only when private local reports/profiles are unavailable.
2. Add a `Resume Analysis` radio option to `app.py`.
3. Add a focused upload helper module or function set for:
   - extension and byte-size validation
   - in-memory DOCX parsing
   - temporary unique processing ID
   - text extraction and section/skill analysis
   - quality validation
   - selected-job matching
   - project matching
   - scoring and downloadable JSON/CSV output
4. Select job descriptions from `job_descriptions/*.json` without logging or storing uploaded text.
5. Reuse the existing section, evidence, matcher, project, quality, and scoring return structures.
6. Keep synthetic/demo and uploaded/analysis data in separate session state namespaces.
7. Extend missing-data handling minimally; do not erase existing report-based features.
8. Add tests around extraction, empty input, analysis, matching, missing jobs/reports, synthetic data, and invalid uploads.
9. Update `.gitignore`, README, requirements, Streamlit configuration, and cloud startup instructions.

## 8. Risks and Deployment Limitations

### Privacy and storage

- Uploaded resumes must not be copied into `Resume docs/`, `extracted_data/`, or `analyzed_data*` by default.
- Streamlit reruns/session state require care so extracted text is not unnecessarily persisted.
- Error strings may expose filenames or parser details; resume contents must never be logged.
- Existing batch folders are presently present locally and may contain private/anonymized candidate data. They must remain excluded and not be committed.

### File parsing

- `resume_parser.py` currently passes paths to `python-docx`; uploaded `UploadedFile` objects require in-memory testing/adapter support.
- Malformed, encrypted, empty, or ZIP-based fake DOCX files can raise exceptions and need explicit handling.
- PDF support is not implemented and should not be added without an approved dependency and security/memory review.

### Experience parsing

- Date extraction recognizes only supported patterns and is intentionally conservative.
- Heading detection and employment grouping can misclassify role titles or date lines.
- Maximum experience boundaries and internship relevance require manual review in ambiguous cases.
- `date.today()` makes experience output time-dependent; tests should fix a date or use a tolerance.

### Education matching

- Education matching is mostly substring-based normalized text, not a qualification ontology or degree-level parser.
- Broad terms such as `related`, `relevant`, or `any field` are sent to manual review.

### Project grouping

- `project_matcher.group_projects()` uses flat line heuristics and can misidentify titles versus descriptions.
- The code reports a grouping note rather than claiming reliable grouping.

### Scoring

- Scores are evidence coverage indicators, not hiring decisions.
- Component coverage and missing components can result in `None` overall scores or partial coverage.
- Rankings are independent within each job, but the dashboard should continue to label them decision-support data.
- `scoring_engine.py` reads `analyzed_data/`, not `analyzed_data_v2/`, so V2 profiles require an integration adapter or directory/schema correction.

### Missing local data

- Batch directories are present now but are excluded by `.gitignore` and may be absent in a clone.
- `app.py` handles absent CSV/JSON files through empty frames and warnings, but the dashboard will not have synthetic candidates until Demo Mode is implemented.
- Top-level import-time directory creation in parser/analyzer modules could create ignored folders in Cloud, but it should not become a substitute for missing private data handling.

### Dependencies and compatibility

- `requirements.txt` is a fully pinned list and includes a Streamlit version, python-docx, Pandas, NumPy, Plotly, and pyarrow.
- Exact version compatibility with the Community Cloud Python runtime should be tested; future-dated package versions may not be available from the deployment runner.
- There is no `.streamlit/config.toml` or `secrets.toml` currently.
- No PDF dependency is installed.
- No test framework dependency or test suite exists yet.

### Relative paths

- Python modules generally use `Path(__file__).resolve().parent`, which is deployment-safe for repository-relative files.
- `app.py` uses project-relative absolute paths derived from `__file__`.
- The app should use a repository-safe synthetic fallback and avoid requiring Cloud filesystem writes.

### Git/Streamlit deployment

- `.gitignore` excludes `.env`, virtual environments, private candidate folders, DOCX/PDF resumes, backups, and Streamlit secrets.
- The private folders are present locally and must not be added if using `git add .`.
- `app.py` is the deployment entry point.
- The repository must include sample only data in Git; synthetic demo JSON/CSV data should be explicitly fictional.
- Streamlit Community Cloud will not have local private folders or local report data unless generated before startup or created from synthetic fallbacks.

## 9. Existing Test Coverage

No `test_*.py`, `*_test.py`, or `tests/` directory was found. Testing is currently absent at the repository level.

## 10. Stage 1 Inspection Record

### Files inspected

- `app.py`
- `resume_parser.py`
- `resume_analyzer.py`
- `resume_analyzer_v2.py`
- `resume_job_matcher.py`
- `resume_job_matcher_fixed.py`
- `resume_job_matcher_backup.py` (via repository listing/import conflict review)
- `data_quality_validator.py`
- `job_description_analyzer.py`
- `project_matcher.py`
- `scoring_engine.py`
- `skill_ontology.json`
- `job_descriptions/lca_consultant.json`
- `job_descriptions/ui_ux_designer.json`
- `requirements.txt`
- `README.md`
- `.gitignore`
- `analyzed_data_v2/all_profiles.json` (schema/sample inspection)

### Repository state

- Private/local candidate folders and resume folders exist locally.
- `.streamlit/` is absent.
- No test files were found.
- No application or documentation files were modified during the audit.

## 11. Remaining Questions for Stage 2 Approval

Before implementation, approval is requested for:

1. The primary implementation choices listed above.
2. Whether synthetic Demo Mode should provide existing app pages with synthetic frames generated in code or with committed JSON/CSV fixture files.
3. Whether upload analysis should add a single modular Python helper file or several small modules.
4. Whether the V2 profile schema should be adopted for `analyzed_data/` compatibility going forward.
