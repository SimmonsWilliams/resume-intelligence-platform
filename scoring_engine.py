"""Score analyzed candidate profiles against the configured job descriptions.

Run after resume_analyzer.py and project_matcher.py:
    python scoring_engine.py

Scores are not hiring decisions. Uncertain evidence is marked for manual review.
"""

import csv
import json
import math
import sys
from pathlib import Path

from resume_job_matcher import match_education, match_experience, match_skills


BASE_DIR = Path(__file__).resolve().parent
CANDIDATE_FILE = BASE_DIR / "analyzed_data" / "all_profiles.json"
JOB_DIR = BASE_DIR / "job_descriptions"
PROJECT_REPORT_FILE = BASE_DIR / "reports" / "project_match_report.json"
QUALITY_REPORT_FILE = BASE_DIR / "reports" / "quality_report.json"
REPORT_DIR = BASE_DIR / "reports"

WEIGHTS = {
    "required_skills_score": 25.0,
    "preferred_skills_score": 10.0,
    "education_score": 15.0,
    "experience_score": 25.0,
    "project_score": 25.0,
}

CSV_FIELDS = [
    "candidate_id",
    "job_id",
    "job_title",
    "required_skills_score",
    "preferred_skills_score",
    "education_score",
    "experience_score",
    "project_score",
    "overall_score",
    "score_coverage",
    "manual_review_required",
    "manual_review_reasons",
    "ranking",
    "evaluation_status",
]


def load_json(path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_candidates():
    if not CANDIDATE_FILE.is_file():
        raise FileNotFoundError(
            "Analyzed candidate data is unavailable: " + str(CANDIDATE_FILE)
        )
    candidates = load_json(CANDIDATE_FILE)
    if not isinstance(candidates, list):
        raise ValueError("all_profiles.json must contain a JSON list.")
    return candidates


def load_jobs():
    if not JOB_DIR.is_dir():
        raise FileNotFoundError(
            "Job descriptions folder is unavailable: " + str(JOB_DIR)
        )
    jobs = []
    for path in sorted(JOB_DIR.glob("*.json")):
        job = load_json(path)
        if not isinstance(job, dict):
            raise ValueError("Job description must contain a JSON object: " + str(path))
        jobs.append(job)
    return jobs


def load_optional_report(path, issues, expected_type):
    if not path.is_file():
        issues.append("Optional input report is unavailable: " + str(path))
        return None
    try:
        report = load_json(path)
    except (OSError, json.JSONDecodeError) as error:
        issues.append(
            "Could not read optional input report "
            + str(path)
            + ": "
            + str(error)
        )
        return None
    if not isinstance(report, expected_type):
        issues.append(
            "Optional input report has an unexpected JSON structure: " + str(path)
        )
        return None
    return report


def _nonempty_id(item):
    value = item.get("candidate_id") if isinstance(item, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _unique_records(records, kind, issues):
    unique = []
    seen = set()
    for index, record in enumerate(records):
        identifier = _nonempty_id(record) if kind == "candidate" else (
            record.get("job_id", "").strip()
            if isinstance(record, dict)
            and isinstance(record.get("job_id"), str)
            and record.get("job_id").strip()
            else None
        )
        if identifier is None:
            issues.append(
                "Skipped "
                + kind
                + " at input position "
                + str(index + 1)
                + " because its identifier is missing or invalid."
            )
            continue
        if identifier in seen:
            issues.append(
                "Skipped duplicate "
                + kind
                + " identifier: "
                + identifier
            )
            continue
        seen.add(identifier)
        unique.append(record)
    return unique


def _text_list(value):
    if not isinstance(value, (list, tuple)):
        return None
    if any(not isinstance(item, str) for item in value):
        return None
    return [item for item in value if item.strip()]


def _finite_nonnegative_number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _new_component(
    weight,
    points=None,
    coverage=0.0,
    note=None,
    requires_review=False,
):
    return {
        "points": points,
        "weight": weight,
        "coverage_fraction": max(0.0, min(1.0, coverage)),
        "note": note,
        "requires_review": requires_review,
    }


def score_skill_component(candidate, job, job_field, match_key, component_name):
    job_skills = _text_list(job.get(job_field))
    if job_field not in job or job_skills is None:
        return _new_component(
            WEIGHTS[component_name],
            note="Job skill requirements are missing or malformed.",
            requires_review=True,
        )
    if not job_skills:
        return _new_component(
            WEIGHTS[component_name],
            note="No " + job_field.replace("_", " ") + " were specified.",
        )

    candidate_skills = _text_list(candidate.get("skills"))
    if "skills" not in candidate or candidate_skills is None:
        return _new_component(
            WEIGHTS[component_name],
            note="Candidate skills are missing or malformed.",
            requires_review=True,
        )

    skill_match = match_skills(candidate_skills, job)
    matched_count = len(skill_match[match_key])
    points = WEIGHTS[component_name] * matched_count / len(job_skills)
    note = None if candidate_skills else "Candidate skills list is empty."
    return _new_component(
        WEIGHTS[component_name],
        points=points,
        coverage=1.0,
        note=note,
        requires_review=not bool(candidate_skills),
    )


def score_education(candidate, job):
    weight = WEIGHTS["education_score"]
    if "education" not in job:
        return _new_component(
            weight,
            note="Job education requirements are missing.",
            requires_review=True,
        )
    required = job.get("education")
    if isinstance(required, str):
        required = [required] if required.strip() else []
    elif isinstance(required, (list, tuple)):
        if any(not isinstance(item, str) for item in required):
            return _new_component(
                weight,
                note="Job education requirements are malformed.",
                requires_review=True,
            )
    else:
        return _new_component(
            weight,
            note="Job education requirements are malformed.",
            requires_review=True,
        )

    if not required:
        return _new_component(weight, note="Education requirement is NOT_SPECIFIED.")

    candidate_education = candidate.get("education")
    if "education" not in candidate or not isinstance(
        candidate_education, (str, list, tuple)
    ):
        return _new_component(
            weight,
            note="Candidate education data is missing or malformed.",
            requires_review=True,
        )

    if not candidate_education:
        return _new_component(
            weight,
            points=0.0,
            coverage=1.0,
            note="Candidate education list is empty.",
            requires_review=True,
        )

    result = match_education(candidate_education, job)
    if result.get("status") == "NOT_SPECIFIED":
        return _new_component(weight, note="Education requirement is NOT_SPECIFIED.")

    matched = result.get("matched", [])
    missing = result.get("missing", [])
    needs_review = result.get("manual_review", [])
    evaluable_count = len(matched) + len(missing)
    requirement_count = evaluable_count + len(needs_review)
    if requirement_count == 0 or evaluable_count == 0:
        return _new_component(
            weight,
            note="No education requirement could be scored automatically.",
            requires_review=True,
        )

    points = weight * len(matched) / requirement_count
    coverage = evaluable_count / requirement_count
    note = (
        "Education evidence requires manual review for: " + ", ".join(needs_review)
        if needs_review
        else None
    )
    return _new_component(
        weight,
        points,
        coverage,
        note,
        requires_review=bool(needs_review),
    )


def score_experience(candidate, job):
    weight = WEIGHTS["experience_score"]
    requirements = job.get("experience")
    if not isinstance(requirements, dict):
        return _new_component(
            weight,
            note="Job experience requirements are missing or malformed.",
            requires_review=True,
        )

    if "minimum_years" not in requirements:
        return _new_component(
            weight,
            note="No minimum experience requirement is specified; maximum is not penalized.",
        )
    minimum_years = _finite_nonnegative_number(requirements.get("minimum_years"))
    if minimum_years is None:
        return _new_component(
            weight,
            note="Minimum experience requirement is malformed.",
            requires_review=True,
        )
    if minimum_years == 0:
        return _new_component(
            weight,
            note="No positive minimum experience requirement is specified; maximum is not penalized.",
        )

    result = match_experience(candidate, job)
    status = result.get("status")
    if status not in ("BELOW_MINIMUM", "WITHIN_RANGE", "ABOVE_MAXIMUM"):
        return _new_component(
            weight,
            note="Relevant non-internship experience needs manual review.",
            requires_review=True,
        )

    months = _finite_nonnegative_number(
        result.get("relevant_employment_experience_months")
    )
    if months is None:
        return _new_component(
            weight,
            note="Relevant non-internship months are unavailable.",
            requires_review=True,
        )

    minimum_months = minimum_years * 12
    points = weight * min(months / minimum_months, 1.0)
    note = None
    if status == "ABOVE_MAXIMUM":
        note = "Preferred maximum experience boundary exceeded; no score penalty applied."
    elif result.get("manual_review"):
        note = "Other experience evidence (including internship relevance) needs review."
    return _new_component(
        weight,
        points,
        1.0,
        note,
        requires_review=bool(result.get("manual_review")),
    )


def _matched_names(value):
    if not isinstance(value, list):
        return None
    names = set()
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            return None
        names.add(item["name"].casefold())
    return names


def score_projects(job, project_result):
    weight = WEIGHTS["project_score"]
    if project_result is None:
        return _new_component(
            weight,
            note="Project match report entry is unavailable.",
            requires_review=True,
        )

    expected_metrics = []
    scored_metrics = []
    notes = []

    project_list = project_result.get("projects")
    project_count = _finite_nonnegative_number(project_result.get("project_count"))
    if isinstance(project_list, list) and project_count is not None:
        expected_metrics.append("project_relevance")
        relevance_names = set()
        for field in (
            "matched_required_skills",
            "matched_preferred_skills",
            "matched_software_tools",
        ):
            matches = _matched_names(project_result.get(field))
            if matches is not None:
                # Names establish relevance; titles in the stored match evidence
                # determine how many distinct projects contain that evidence.
                for item in project_result[field]:
                    if item["name"].casefold() not in matches:
                        continue
                    for evidence in item.get("evidence", []):
                        if isinstance(evidence, dict) and isinstance(
                            evidence.get("project_title"), str
                        ):
                            relevance_names.add(evidence["project_title"].casefold())
            else:
                notes.append("Project relevance evidence is malformed.")
        if project_count == 0:
            relevance_ratio = 0.0
        else:
            relevance_ratio = min(len(relevance_names) / project_count, 1.0)
        scored_metrics.append(relevance_ratio)
    else:
        expected_metrics.append("project_relevance")
        notes.append("Project list or count is unavailable in the project report.")

    required_skills = _text_list(job.get("required_skills"))
    if required_skills:
        expected_metrics.append("project_required_skills")
        matched = _matched_names(project_result.get("matched_required_skills"))
        if matched is None:
            notes.append("Project required-skill matches are unavailable.")
        else:
            denominator = len({skill.casefold() for skill in required_skills})
            scored_metrics.append(
                len(matched.intersection(skill.casefold() for skill in required_skills))
                / denominator
            )

    tools = _text_list(job.get("software_tools"))
    if tools:
        expected_metrics.append("project_software_tools")
        matched = _matched_names(project_result.get("matched_software_tools"))
        if matched is None:
            notes.append("Project software-tool matches are unavailable.")
        else:
            denominator = len({tool.casefold() for tool in tools})
            scored_metrics.append(
                len(matched.intersection(tool.casefold() for tool in tools))
                / denominator
            )

    experience = job.get("experience")
    if isinstance(experience, dict) and "minimum_projects" in experience:
        minimum_projects = _finite_nonnegative_number(experience["minimum_projects"])
        if minimum_projects is None:
            expected_metrics.append("minimum_project_count")
            notes.append("Minimum project requirement is malformed.")
        elif minimum_projects > 0:
            expected_metrics.append("minimum_project_count")
            if project_count is None:
                notes.append("Project count is unavailable for the minimum requirement.")
            else:
                scored_metrics.append(min(project_count / minimum_projects, 1.0))

    if not expected_metrics or not scored_metrics:
        return _new_component(
            weight,
            note="No project dimensions could be scored. "
            + "; ".join(notes),
            requires_review=True,
        )

    coverage = len(scored_metrics) / len(expected_metrics)
    points = weight * sum(scored_metrics) / len(expected_metrics)
    return _new_component(
        weight,
        points,
        coverage,
        "; ".join(notes) or None,
        requires_review=bool(notes),
    )


def _project_result_index(project_report, issues):
    index = {}
    if project_report is None:
        return index
    for position, result in enumerate(project_report):
        if not isinstance(result, dict):
            issues.append(
                "Skipped malformed project report row at position "
                + str(position + 1)
                + "."
            )
            continue
        candidate_id = result.get("candidate_id")
        job_id = result.get("job_id")
        if not isinstance(candidate_id, str) or not isinstance(job_id, str):
            issues.append("Skipped project report row without candidate_id/job_id.")
            continue
        key = (candidate_id, job_id)
        if key in index:
            issues.append(
                "Duplicate project report entry for "
                + candidate_id
                + " / "
                + job_id
                + "; the first entry was used."
            )
            continue
        index[key] = result
    return index


def _quality_index(quality_report):
    if quality_report is None:
        return {}
    return {
        item.get("candidate_id"): item
        for item in quality_report
        if isinstance(item, dict) and isinstance(item.get("candidate_id"), str)
    }


def _append_reason(reasons, reason):
    if isinstance(reason, str) and reason.strip() and reason not in reasons:
        reasons.append(reason.strip())


def evaluate_candidate_job(candidate, job, project_result, quality_result):
    candidate_id = candidate["candidate_id"].strip()
    job_id = job["job_id"].strip()
    reasons = []
    candidate_flags = candidate.get("manual_review")
    if candidate.get("verification_required") is True:
        _append_reason(reasons, "Candidate profile is marked verification_required.")
    if isinstance(candidate_flags, list):
        for reason in candidate_flags:
            _append_reason(reasons, str(reason))

    if quality_result:
        if quality_result.get("validation_status") != "VALID":
            _append_reason(
                reasons,
                "Data quality status: "
                + str(quality_result.get("validation_status", "unknown"))
                + ".",
            )
        for issue in quality_result.get("issues", []):
            _append_reason(reasons, "Data quality issue: " + str(issue))
        for warning in quality_result.get("warnings", []):
            _append_reason(reasons, "Data quality warning: " + str(warning))

    components = {
        "required_skills_score": score_skill_component(
            candidate,
            job,
            "required_skills",
            "matched_required",
            "required_skills_score",
        ),
        "preferred_skills_score": score_skill_component(
            candidate,
            job,
            "preferred_skills",
            "matched_preferred",
            "preferred_skills_score",
        ),
        "education_score": score_education(candidate, job),
        "experience_score": score_experience(candidate, job),
        "project_score": score_projects(job, project_result),
    }

    for name, component in components.items():
        if component["note"]:
            if component["requires_review"]:
                _append_reason(
                    reasons,
                    name.replace("_score", "") + ": " + component["note"],
                )

    weighted_capacity = sum(
        component["weight"] * component["coverage_fraction"]
        for component in components.values()
    )
    earned_points = sum(
        component["points"] or 0.0
        for component in components.values()
    )
    overall_score = (
        earned_points / weighted_capacity * 100.0
        if weighted_capacity > 0
        else None
    )
    score_coverage = weighted_capacity

    if project_result is None:
        _append_reason(reasons, "Project match report entry is missing for this candidate/job pair.")
    elif project_result.get("status") == "NO_PROJECT_DATA":
        _append_reason(reasons, "Project matcher found no project data.")
    if project_result and project_result.get("projects") and project_result.get("grouping_note"):
        _append_reason(reasons, str(project_result["grouping_note"]))

    if reasons:
        evaluation_status = "MANUAL_REVIEW"
    elif score_coverage < 100.0:
        evaluation_status = "PARTIAL_DATA"
    else:
        evaluation_status = "EVALUATED"

    record = {
        "candidate_id": candidate_id,
        "job_id": job_id,
        "job_title": job.get("job_title"),
        "required_skills_score": components["required_skills_score"]["points"],
        "preferred_skills_score": components["preferred_skills_score"]["points"],
        "education_score": components["education_score"]["points"],
        "experience_score": components["experience_score"]["points"],
        "project_score": components["project_score"]["points"],
        "overall_score": overall_score,
        "score_coverage": score_coverage,
        "manual_review_required": bool(reasons),
        "manual_review_reasons": reasons,
        "ranking": None,
        "evaluation_status": evaluation_status,
        "component_coverage": {
            name: round(component["coverage_fraction"] * 100.0, 2)
            for name, component in components.items()
        },
        "component_notes": {
            name: component["note"]
            for name, component in components.items()
            if component["note"]
        },
    }
    return record


def _ranking_key(record):
    score = record.get("overall_score")
    return (
        score is None,
        -(score if score is not None else 0.0),
        record["candidate_id"],
    )


def rank_records(records, jobs):
    ranked = []
    for job in jobs:
        job_id = job["job_id"].strip()
        group = sorted(
            (record for record in records if record["job_id"] == job_id),
            key=_ranking_key,
        )
        for rank, record in enumerate(group, start=1):
            record["ranking"] = rank
            ranked.append(record)
    return ranked


def _csv_row(record):
    row = {field: record.get(field) for field in CSV_FIELDS}
    row["manual_review_required"] = str(record["manual_review_required"]).lower()
    row["manual_review_reasons"] = json.dumps(
        record["manual_review_reasons"], ensure_ascii=False
    )
    return row


def _write_csv(path, records):
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(_csv_row(record) for record in records)


def _validate_records(records, jobs):
    pairs = [(record["candidate_id"], record["job_id"]) for record in records]
    if len(pairs) != len(set(pairs)):
        raise ValueError("Duplicate candidate/job evaluations were generated.")

    for record in records:
        if record["score_coverage"] < 0 or record["score_coverage"] > 100.000001:
            raise ValueError("Score coverage is outside the 0-100 range.")
        for key in WEIGHTS:
            score = record[key]
            if score is not None and (score < 0 or score > WEIGHTS[key] + 0.000001):
                raise ValueError(key + " exceeds its configured weight.")
        overall = record["overall_score"]
        if overall is not None and (overall < 0 or overall > 100.000001):
            raise ValueError("Overall score is outside the 0-100 range.")

    for job in jobs:
        job_records = [
            record for record in records if record["job_id"] == job["job_id"]
        ]
        scores = [
            record["overall_score"]
            for record in job_records
            if record["overall_score"] is not None
        ]
        if scores != sorted(scores, reverse=True):
            raise ValueError("Candidate ranking is not sorted by descending score.")


def _verify_reports(json_paths, csv_paths, expected_rows):
    for path in json_paths:
        data = load_json(path)
        if path.name == "final_scoring_report.json":
            actual_rows = len(data.get("records", []))
        else:
            actual_rows = len(data.get("rankings", []))
        if actual_rows != expected_rows:
            raise ValueError("Generated JSON report row count does not match evaluations: " + str(path))
    for path in csv_paths:
        with path.open("r", newline="", encoding="utf-8-sig") as file:
            actual_rows = sum(1 for _ in csv.DictReader(file))
        if actual_rows != expected_rows:
            raise ValueError("Generated CSV report row count does not match evaluations: " + str(path))


def run():
    issues = []
    candidates = _unique_records(load_candidates(), "candidate", issues)
    jobs = _unique_records(load_jobs(), "job", issues)

    project_report = load_optional_report(
        PROJECT_REPORT_FILE, issues, list
    )
    quality_report = load_optional_report(
        QUALITY_REPORT_FILE, issues, list
    )
    project_index = _project_result_index(project_report, issues)
    quality_index = _quality_index(quality_report)

    records = []
    for candidate in candidates:
        for job in jobs:
            candidate_id = candidate["candidate_id"].strip()
            job_id = job["job_id"].strip()
            project_result = project_index.get((candidate_id, job_id))
            quality_result = quality_index.get(candidate_id)
            records.append(
                evaluate_candidate_job(
                    candidate,
                    job,
                    project_result,
                    quality_result,
                )
            )

    ranked_records = rank_records(records, jobs)
    _validate_records(ranked_records, jobs)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    scoring_json = REPORT_DIR / "final_scoring_report.json"
    scoring_csv = REPORT_DIR / "final_scoring_report.csv"
    ranking_json = REPORT_DIR / "candidate_ranking.json"
    ranking_csv = REPORT_DIR / "candidate_ranking.csv"

    scoring_payload = {
        "scoring_weights": WEIGHTS,
        "normalization": (
            "Overall score = earned points divided by the weighted capacity "
            "of scored evidence, multiplied by 100. Score coverage is the "
            "weighted capacity available out of 100. Unspecified or unavailable "
            "components are excluded from both the earned points and capacity."
        ),
        "records": ranked_records,
        "input_issues": issues,
    }
    ranking_payload = {
        "ranking_scope": "Candidates are ranked independently within each job.",
        "rankings": ranked_records,
    }
    with scoring_json.open("w", encoding="utf-8") as file:
        json.dump(scoring_payload, file, ensure_ascii=False, indent=2)
    with ranking_json.open("w", encoding="utf-8") as file:
        json.dump(ranking_payload, file, ensure_ascii=False, indent=2)
    _write_csv(scoring_csv, ranked_records)
    _write_csv(ranking_csv, ranked_records)
    _verify_reports(
        [scoring_json, ranking_json],
        [scoring_csv, ranking_csv],
        len(ranked_records),
    )

    print("========== FINAL SCORING ==========")
    print("Total candidates:", len(candidates))
    print("Total jobs:", len(jobs))
    print("Unique evaluations:", len(ranked_records))
    for job in jobs:
        job_records = [
            record for record in ranked_records if record["job_id"] == job["job_id"]
        ]
        print(
            "\nJob:",
            job.get("job_title"),
            "| Candidates evaluated:",
            len(job_records),
        )
        print(
            "Manual review count:",
            sum(record["manual_review_required"] for record in job_records),
        )
        average_coverage = (
            sum(record["score_coverage"] for record in job_records) / len(job_records)
            if job_records
            else 0.0
        )
        print("Average data coverage: {:.2f}%".format(average_coverage))
        print("Top 10 candidates:")
        for record in job_records[:10]:
            component_summary = ", ".join(
                "{}={}".format(
                    field.replace("_score", ""),
                    "N/A" if record[field] is None else "{:.2f}".format(record[field]),
                )
                for field in WEIGHTS
            )
            overall = (
                "N/A"
                if record["overall_score"] is None
                else "{:.2f}".format(record["overall_score"])
            )
            print(
                "  #{:02d} {} | Overall: {} | {} | Coverage: {:.2f}% | Manual review: {}".format(
                    record["ranking"],
                    record["candidate_id"],
                    overall,
                    component_summary,
                    record["score_coverage"],
                    "yes" if record["manual_review_required"] else "no",
                )
            )

    if issues:
        print("\nInput issues:")
        for issue in issues:
            print("- " + issue)
    print("\nReports generated:")
    for path in (scoring_json, scoring_csv, ranking_json, ranking_csv):
        print(path.relative_to(BASE_DIR))
    print("===================================")


def main():
    try:
        run()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print("ERROR: scoring_engine failed: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
