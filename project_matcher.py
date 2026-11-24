from pathlib import Path
import json
import csv
import re

BASE_DIR = Path(__file__).resolve().parent
CANDIDATE_FILE = BASE_DIR / "analyzed_data" / "all_profiles.json"
JOB_DIR = BASE_DIR / "job_descriptions"
REPORT_DIR = BASE_DIR / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# These verbs commonly begin project descriptions rather than project titles.
DESCRIPTION_STARTERS = {
    "built", "created", "developed", "designed", "implemented", "implemented",
    "engineered", "evaluated", "analyzed", "analysed", "optimized", "modelled",
    "modeled", "recognized", "authored", "published", "automated", "deployed",
    "used", "utilized", "utilised", "streamlined", "conducted", "integrated",
    "configured", "tested", "managed", "performed", "generated", "trained",
    "predicted", "classified", "visualized", "visualised", "maintained"
}


def load_candidates():
    """Load candidates produced by resume_analyzer.py."""
    if not CANDIDATE_FILE.exists():
        raise FileNotFoundError(f"Candidate data not found: {CANDIDATE_FILE}")
    with CANDIDATE_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError("all_profiles.json must contain a JSON list.")
    return data


def load_jobs():
    """Load every JSON job description from job_descriptions/."""
    if not JOB_DIR.exists():
        raise FileNotFoundError(f"Job descriptions folder not found: {JOB_DIR}")
    jobs = []
    for path in sorted(JOB_DIR.glob("*.json")):
        with path.open("r", encoding="utf-8") as file:
            job = json.load(file)
        job["_source_file"] = path.name
        jobs.append(job)
    return jobs


def clean_project_line(value):
    """Remove common bullet characters and surrounding whitespace."""
    text = str(value).strip()
    text = re.sub(r"^[\s•*\-–—]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def starts_like_description(text):
    """Return True when a line appears to describe work done in a project."""
    if not text:
        return False
    first_word = re.sub(r"[^a-z]", "", text.casefold().split()[0])
    return first_word in DESCRIPTION_STARTERS


def group_projects(project_lines):
    """Convert the analyzer's flat project list into title + description groups.

    The current analyzer output stores titles and description lines in one list.
    A new non-description line starts a new project; description-like lines are
    attached to the most recent title. Ambiguous lines are retained and flagged.
    """
    projects = []
    unassigned_lines = []

    for raw_line in project_lines or []:
        line = clean_project_line(raw_line)
        if not line:
            continue

        if starts_like_description(line) and projects:
            projects[-1]["description_lines"].append(line)
        elif not projects:
            projects.append({"title": line, "description_lines": [], "grouping_note": "First non-description line treated as title."})
        else:
            projects.append({"title": line, "description_lines": [], "grouping_note": "Non-description line treated as a new title."})

    for project in projects:
        project["full_text"] = " ".join([project["title"], *project["description_lines"]])

    return projects, unassigned_lines


def normalize(text):
    return re.sub(r"\s+", " ", str(text or "")).casefold().strip()


def find_phrase_matches(projects, phrases):
    """Find literal phrase evidence; deliberately avoids speculative fuzzy matches."""
    matches = []
    for phrase in phrases or []:
        needle = normalize(phrase)
        if not needle:
            continue
        evidence = []
        for project in projects:
            if needle in normalize(project["full_text"]):
                evidence.append({
                    "project_title": project["title"],
                    "matched_text": phrase
                })
        if evidence:
            matches.append({"name": phrase, "evidence": evidence})
    return matches


def match_candidate_projects(candidate, job):
    raw_projects = candidate.get("projects", [])
    projects, _ = group_projects(raw_projects)

    required_skills = job.get("required_skills") or []
    preferred_skills = job.get("preferred_skills") or []
    software_tools = job.get("software_tools") or []
    experience = job.get("experience") or {}
    minimum_projects = experience.get("minimum_projects")

    required_matches = find_phrase_matches(projects, required_skills)
    preferred_matches = find_phrase_matches(projects, preferred_skills)
    tool_matches = find_phrase_matches(projects, software_tools)

    matched_required_names = {item["name"] for item in required_matches}
    matched_preferred_names = {item["name"] for item in preferred_matches}
    matched_tool_names = {item["name"] for item in tool_matches}

    missing_required = [s for s in required_skills if s not in matched_required_names]
    missing_preferred = [s for s in preferred_skills if s not in matched_preferred_names]
    missing_tools = [s for s in software_tools if s not in matched_tool_names]

    project_count_evaluated = minimum_projects is not None
    project_count_met = (len(projects) >= minimum_projects) if project_count_evaluated else None

    if not projects:
        status = "NO_PROJECT_DATA"
    elif project_count_evaluated and not project_count_met:
        status = "BELOW_MINIMUM_PROJECT_COUNT"
    elif missing_required or missing_tools:
        status = "PARTIAL_MATCH"
    else:
        status = "MATCHED"

    return {
        "candidate_id": candidate.get("candidate_id", ""),
        "source_file": candidate.get("source_file", ""),
        "job_id": job.get("job_id", ""),
        "job_title": job.get("job_title", ""),
        "status": status,
        "project_count": len(projects),
        "minimum_projects": minimum_projects,
        "project_count_evaluated": project_count_evaluated,
        "project_count_met": project_count_met,
        "projects": projects,
        "matched_required_skills": required_matches,
        "missing_required_skills": missing_required,
        "matched_preferred_skills": preferred_matches,
        "missing_preferred_skills": missing_preferred,
        "matched_software_tools": tool_matches,
        "missing_software_tools": missing_tools,
        "grouping_note": (
            "Project titles/descriptions were inferred from the flat analyzer list. "
            "Please review project grouping when a line could be interpreted either way."
        )
    }


def write_reports(results):
    json_path = REPORT_DIR / "project_match_report.json"
    csv_path = REPORT_DIR / "project_match_report.csv"

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(results, file, indent=4, ensure_ascii=False)

    columns = [
        "candidate_id", "job_id", "job_title", "status", "project_count",
        "minimum_projects", "project_count_met", "matched_required_count",
        "missing_required_count", "matched_preferred_count", "matched_tools_count"
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for item in results:
            writer.writerow({
                "candidate_id": item["candidate_id"],
                "job_id": item["job_id"],
                "job_title": item["job_title"],
                "status": item["status"],
                "project_count": item["project_count"],
                "minimum_projects": item["minimum_projects"],
                "project_count_met": item["project_count_met"],
                "matched_required_count": len(item["matched_required_skills"]),
                "missing_required_count": len(item["missing_required_skills"]),
                "matched_preferred_count": len(item["matched_preferred_skills"]),
                "matched_tools_count": len(item["matched_software_tools"])
            })
    return json_path, csv_path


def main():
    candidates = load_candidates()
    jobs = load_jobs()
    print("========== PROJECT MATCHING ENGINE ==========")
    print(f"Total Candidates: {len(candidates)}")
    print(f"Total Jobs: {len(jobs)}")

    results = []
    for candidate in candidates:
        for job in jobs:
            results.append(match_candidate_projects(candidate, job))

    for job in jobs:
        job_results = [r for r in results if r["job_id"] == job.get("job_id")]
        counts = {}
        for result in job_results:
            counts[result["status"]] = counts.get(result["status"], 0) + 1
        print(f"\nJob: {job.get('job_title', 'Unknown')}")
        print(f"Candidates evaluated: {len(job_results)}")
        for status, count in sorted(counts.items()):
            print(f"{status}: {count}")

    first_candidate = candidates[0] if candidates else None
    first_job = jobs[0] if jobs else None
    if first_candidate and first_job:
        detail = match_candidate_projects(first_candidate, first_job)
        print("\n========== FIRST CANDIDATE DETAIL ==========")
        print(f"Candidate: {detail['candidate_id']}")
        print(f"Job: {detail['job_title']}")
        print(f"Status: {detail['status']}")
        print(f"Projects identified: {detail['project_count']}")
        if detail["minimum_projects"] is not None:
            print(f"Minimum projects required: {detail['minimum_projects']}")
            print(f"Project count met: {detail['project_count_met']}")
        for index, project in enumerate(detail["projects"], start=1):
            print(f"\nProject {index}: {project['title']}")
            for line in project["description_lines"]:
                print(f"  - {line}")
        print("\nMatched required skills:")
        for item in detail["matched_required_skills"]:
            print(f"+ {item['name']}")
        print("Missing required skills:")
        for item in detail["missing_required_skills"]:
            print(f"- {item}")
        print("Matched software tools:")
        for item in detail["matched_software_tools"]:
            print(f"+ {item['name']}")
        print("Missing software tools:")
        for item in detail["missing_software_tools"]:
            print(f"- {item}")

    json_path, csv_path = write_reports(results)
    print("\nReports Generated:")
    print(json_path.relative_to(BASE_DIR))
    print(csv_path.relative_to(BASE_DIR))
    print("=============================================")


if __name__ == "__main__":
    main()
