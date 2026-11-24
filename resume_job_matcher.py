
import json
import re
from datetime import date, datetime

from pathlib import Path


# ==================================
# SKILL NORMALIZATION
# ==================================

SKILL_ALIASES = {
    "lca": "life cycle assessment",
    "life-cycle assessment": "life cycle assessment",
    "life cycle analysis": "life cycle assessment",
}


def normalize_skill(skill):

    skill = skill.strip().lower()

    return SKILL_ALIASES.get(skill, skill)


# ==================================
# SKILL MATCHING ENGINE
# ==================================

def match_skills(candidate_skills, job):

    required_skills = job.get(
        "required_skills", []
    )

    preferred_skills = job.get(
        "preferred_skills", []
    )

    candidate_normalized = {
        normalize_skill(skill)
        for skill in candidate_skills
    }

    matched_required = []
    missing_required = []

    matched_preferred = []
    missing_preferred = []

    # Required Skills Matching
    for skill in required_skills:

        normalized = normalize_skill(skill)

        if normalized in candidate_normalized:

            matched_required.append(skill)

        else:

            missing_required.append(skill)

    # Preferred Skills Matching
    for skill in preferred_skills:

        normalized = normalize_skill(skill)

        if normalized in candidate_normalized:

            matched_preferred.append(skill)

        else:

            missing_preferred.append(skill)

    return {

        "matched_required": matched_required,

        "missing_required": missing_required,

        "matched_preferred": matched_preferred,

        "missing_preferred": missing_preferred

    }

# ==================================
# EDUCATION MATCHING ENGINE
# ==================================

def normalize_education(text):

    import re

    if not isinstance(text, str):
        return ""

    text = text.lower()

    text = re.sub(r"[^a-z0-9\s]", " ", text)

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def match_education(candidate_education, job):

    if not isinstance(job, dict):
        required_education = []
    else:
        required_education = job.get("education", [])

    if isinstance(required_education, str):
        required_education = [required_education]
    elif not isinstance(required_education, (list, tuple)):
        required_education = []

    required_education = [
        requirement
        for requirement in required_education
        if isinstance(requirement, str) and requirement.strip()
    ]

    # Job has no specified education requirement
    if not required_education:

        return {
            "status": "NOT_SPECIFIED",
            "matched": [],
            "missing": [],
            "manual_review": [],
            "evidence": []
        }

    matched = []
    missing = []
    manual_review = []
    evidence = []

    if isinstance(candidate_education, str):
        candidate_education = [candidate_education]
    elif not isinstance(candidate_education, (list, tuple)):
        candidate_education = []

    normalized_candidate = [
        (item, normalize_education(item))
        for item in candidate_education
        if isinstance(item, str) and normalize_education(item)
    ]
    seen_requirements = set()
    seen_evidence = set()

    for requirement in required_education:

        normalized_requirement = normalize_education(
            requirement
        )

        if not normalized_requirement or normalized_requirement in seen_requirements:
            continue

        seen_requirements.add(normalized_requirement)

        # Broad domain requirements cannot be reliably classified automatically.
        if any(marker in normalized_requirement for marker in (
            "related",
            "relevant",
            "or equivalent",
            "any field",
            "any discipline",
            "similar field",
        )):
            manual_review.append(requirement)
            continue

        matching_evidence = [
            original
            for original, normalized in normalized_candidate
            if normalized_requirement in normalized
        ]

        if matching_evidence:
            matched.append(requirement)

            for item in matching_evidence:
                if item not in seen_evidence:
                    evidence.append(item)
                    seen_evidence.add(item)

        else:
            missing.append(requirement)

    return {
        "status": "EVALUATED",
        "matched": matched,
        "missing": missing,
        "manual_review": manual_review,
        "evidence": evidence
    }


# ==================================
# EXPERIENCE MATCHING ENGINE
# ==================================

EXPERIENCE_MONTH_PATTERN = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|"
    r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)

EXPERIENCE_DATE_RANGE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?P<start>(?:" + EXPERIENCE_MONTH_PATTERN + r")\s+\d{4}|\d{4})"
    r"\s*(?:-|–|—|\bto\b)\s*"
    r"(?P<end>(?:" + EXPERIENCE_MONTH_PATTERN + r")\s+\d{4}|"
    r"\d{4}|present|current|now)"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _experience_text_entries(value):

    if isinstance(value, str):
        value = [value]

    if not isinstance(value, (list, tuple)):
        return []

    return [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]


def _parse_experience_date(value, current_date):

    value = value.strip()

    if value.lower() in ("present", "current", "now"):
        return current_date.year * 12 + current_date.month - 1

    if value.isdigit():
        return int(value) * 12

    for date_format in ("%B %Y", "%b %Y"):
        try:
            parsed = datetime.strptime(value, date_format)
            return parsed.year * 12 + parsed.month - 1
        except ValueError:
            continue

    raise ValueError("Unsupported experience date")


def _parse_experience_date_range(text, current_date):

    match = EXPERIENCE_DATE_RANGE_PATTERN.search(text)

    if not match:
        return None

    try:
        start_month = _parse_experience_date(
            match.group("start"),
            current_date
        )
        end_month = _parse_experience_date(
            match.group("end"),
            current_date
        )
    except ValueError:
        return {"error": "Experience date range could not be parsed."}

    if end_month < start_month:
        return {"error": "Experience end date is earlier than its start date."}

    return {
        "start_month": start_month,
        "end_month": end_month,
        "start_date": match.group("start"),
        "end_date": match.group("end"),
    }


def _looks_like_experience_heading(text):

    if text.startswith(("•", "-", "*")):
        return False

    return bool(re.search(
        r"\b(intern|internship|engineer|analyst|manager|developer|"
        r"designer|consultant|associate|trainee|specialist|officer)\b",
        text,
        re.IGNORECASE
    ))


def extract_employment_entries(candidate, current_date=None):

    if not isinstance(candidate, dict):
        return [], False

    current_date = current_date or date.today()
    experience = _experience_text_entries(candidate.get("experience"))
    evidence = _experience_text_entries(
        candidate.get("experience_evidence")
    )

    combined_entries = []
    seen_text = set()

    for item in experience + evidence:
        if item not in seen_text:
            combined_entries.append(item)
            seen_text.add(item)

    fresher_text = " ".join(
        combined_entries
        + _experience_text_entries(candidate.get("experience_level"))
    )
    explicitly_fresher = bool(re.search(
        r"\bfresher\b|\bno (?:prior |professional )?experience\b",
        fresher_text,
        re.IGNORECASE
    ))

    experience_markers = re.compile(
        r"^\s*(?:fresher|no (?:prior |professional )?experience)\s*[.!]*\s*$",
        re.IGNORECASE,
    )
    combined_entries = [
        item for item in combined_entries
        if not experience_markers.match(item)
    ]

    if explicitly_fresher and not combined_entries:
        return [], True

    employment_entries = []
    current_entry = None

    for item in combined_entries:
        parsed_range = _parse_experience_date_range(item, current_date)

        if parsed_range is not None:
            if (
                current_entry is not None
                and current_entry["date_status"] != "PARSED"
                and current_entry.get("date_issue")
                == "No supported employment date range was found."
            ):
                current_entry.update({
                    "start_date": parsed_range.get("start_date"),
                    "end_date": parsed_range.get("end_date"),
                    "duration_months": (
                        parsed_range["end_month"] - parsed_range["start_month"]
                        if "error" not in parsed_range
                        else None
                    ),
                    "date_status": (
                        "PARSED" if "error" not in parsed_range
                        else "MANUAL_REVIEW"
                    ),
                    "_start_month": parsed_range.get("start_month"),
                    "_end_month": parsed_range.get("end_month"),
                })
                if "error" in parsed_range:
                    current_entry["date_issue"] = parsed_range["error"]
                if item not in current_entry["evidence"]:
                    current_entry["evidence"].append(item)
                continue

            current_entry = {
                "original_text": item,
                "evidence": [item],
                "employment_type": (
                    "INTERNSHIP"
                    if re.search(r"\bintern(?:ship)?\b", item, re.IGNORECASE)
                    else "EMPLOYMENT"
                ),
                "start_date": None,
                "end_date": None,
                "duration_months": None,
                "date_status": "MANUAL_REVIEW",
                "_start_month": None,
                "_end_month": None,
            }

            if "error" in parsed_range:
                current_entry["date_issue"] = parsed_range["error"]
            else:
                current_entry.update({
                    "start_date": parsed_range["start_date"],
                    "end_date": parsed_range["end_date"],
                    "duration_months": (
                        parsed_range["end_month"]
                        - parsed_range["start_month"]
                    ),
                    "date_status": "PARSED",
                    "_start_month": parsed_range["start_month"],
                    "_end_month": parsed_range["end_month"],
                })

            employment_entries.append(current_entry)
            continue

        if current_entry is None or _looks_like_experience_heading(item):
            current_entry = {
                "original_text": item,
                "evidence": [item],
                "employment_type": (
                    "INTERNSHIP"
                    if re.search(r"\bintern(?:ship)?\b", item, re.IGNORECASE)
                    else "EMPLOYMENT"
                ),
                "start_date": None,
                "end_date": None,
                "duration_months": None,
                "date_status": "MANUAL_REVIEW",
                "date_issue": "No supported employment date range was found.",
                "_start_month": None,
                "_end_month": None,
            }
            employment_entries.append(current_entry)
        elif item not in current_entry["evidence"]:
            current_entry["evidence"].append(item)

    return employment_entries, explicitly_fresher


def _merged_period_months(entries):

    periods = sorted(
        (entry["_start_month"], entry["_end_month"])
        for entry in entries
        if entry["date_status"] == "PARSED"
    )

    if not periods:
        return 0

    total_months = 0
    period_start, period_end = periods[0]

    for start, end in periods[1:]:
        if start <= period_end:
            period_end = max(period_end, end)
        else:
            total_months += period_end - period_start
            period_start, period_end = start, end

    return total_months + period_end - period_start


def _job_relevance_terms(job):

    if not isinstance(job, dict):
        return set()

    source_values = _experience_text_entries(job.get("job_title"))
    for field in (
        "required_skills",
        "preferred_skills",
        "software_tools",
    ):
        source_values.extend(_experience_text_entries(job.get(field)))

    generic_phrases = {
        "experience",
        "management",
        "assessment",
        "engineering",
        "consultant",
        "designer",
        "design",
        "professional",
        "required",
    }
    return {
        phrase
        for value in source_values
        for phrase in [" ".join(re.findall(r"[a-z0-9]+", value.lower()))]
        if phrase and phrase not in generic_phrases
    }


def _experience_domain_tags(text):
    """Return broad, explainable domains found in resume/job evidence."""

    normalized = " ".join(re.findall(r"[a-z0-9]+", str(text).lower()))
    tags = set()

    if re.search(
        r"\b(environment|environmental|sustainability|sustainable|carbon|"
        r"greenhouse|ghg|emission|pollution|life cycle|lca|openlca|gabi|"
        r"simapro|cpcb|cems|effluent|wastewater)\b",
        normalized,
    ):
        tags.add("environment")

    if re.search(
        r"\b(ui ux|ux ui|user interface|user experience|figma|"
        r"prototyp|wirefram|user research|responsive design|visual design)\b",
        normalized,
    ):
        tags.add("design")

    if re.search(
        r"\b(solar|photovoltaic|renewable energy|power plant|energy)\b",
        normalized,
    ):
        tags.add("energy")

    if re.search(
        r"\b(java|python|javascript|software|programming|developer|"
        r"backend|frontend|database|api)\b",
        normalized,
    ):
        tags.add("software")

    return tags


def _entry_relevance(entry, job, relevance_phrases):
    """Classify relevance using exact phrases first, then domain evidence."""

    evidence = entry.get("evidence", [])
    normalized_evidence = [
        (item, " ".join(re.findall(r"[a-z0-9]+", item.lower())))
        for item in evidence
    ]

    matched_phrases = sorted(
        phrase
        for phrase in relevance_phrases
        if any(
            " " + phrase + " " in " " + normalized_text + " "
            for _, normalized_text in normalized_evidence
        )
    )

    if matched_phrases:
        matching_evidence = [
            item
            for item, normalized_text in normalized_evidence
            if any(
                " " + phrase + " " in " " + normalized_text + " "
                for phrase in matched_phrases
            )
        ]
        return True, "RELEVANT", matched_phrases, matching_evidence

    job_text = " ".join(
        _experience_text_entries(job.get("job_title"))
        + _experience_text_entries(job.get("required_skills"))
        + _experience_text_entries(job.get("preferred_skills"))
        + _experience_text_entries(job.get("software_tools"))
    ) if isinstance(job, dict) else ""

    candidate_text = " ".join(evidence)
    job_domains = _experience_domain_tags(job_text)
    candidate_domains = _experience_domain_tags(candidate_text)
    overlapping_domains = sorted(job_domains & candidate_domains)

    if overlapping_domains:
        matching_evidence = [
            item for item, _ in normalized_evidence
            if _experience_domain_tags(item) & set(overlapping_domains)
        ]
        return (
            True,
            "RELEVANT_DOMAIN_OVERLAP",
            ["domain: " + ", ".join(overlapping_domains)],
            matching_evidence,
        )

    # A domain mismatch is useful evidence for employment, but internship
    # relevance is kept conservative because internships may be adjacent.
    if job_domains and candidate_domains and entry.get("employment_type") != "INTERNSHIP":
        return False, "NOT_RELEVANT", [], []

    return None, "MANUAL_REVIEW", [], []

def _format_experience_years(years):

    return str(int(years)) if years == int(years) else str(years)


def match_experience(candidate, job, current_date=None):

    current_date = current_date or date.today()
    employment_entries, explicitly_fresher = extract_employment_entries(
        candidate,
        current_date
    )

    relevance_phrases = _job_relevance_terms(job)
    manual_review = []

    for entry in employment_entries:
        relevant, relevance_status, matched_phrases, matching_evidence = (
            _entry_relevance(entry, job, relevance_phrases)
        )
        entry["relevance_terms"] = matched_phrases
        entry["relevant"] = relevant
        entry["relevance_status"] = relevance_status
        entry["relevance_evidence"] = matching_evidence

        if entry["date_status"] != "PARSED":
            manual_review.append(
                entry.get("date_issue", "Employment dates need manual review.")
                + " Evidence: "
                + entry["original_text"]
            )

        if relevance_status == "MANUAL_REVIEW":
            manual_review.append(
                "Role relevance needs manual review; evidence does not establish "
                "a reliable job-domain match: " + entry["original_text"]
            )

    total_months = _merged_period_months(employment_entries)
    employment_months = _merged_period_months([
        entry for entry in employment_entries
        if entry["employment_type"] != "INTERNSHIP"
    ])
    internship_months = _merged_period_months([
        entry for entry in employment_entries
        if entry["employment_type"] == "INTERNSHIP"
    ])
    relevant_employment_entries = [
        entry for entry in employment_entries
        if (
            entry["employment_type"] != "INTERNSHIP"
            and entry["relevant"] is True
        )
    ]
    relevant_employment_months = _merged_period_months(
        relevant_employment_entries
    )
    relevant_months = _merged_period_months([
        entry for entry in employment_entries
        if entry["relevant"] is True
    ])

    matched_requirements = []
    missing_requirements = []
    malformed_requirements = False
    invalid_threshold = False
    requirement_data = job.get("experience") if isinstance(job, dict) else None

    if requirement_data is None:
        requirement_data = {}
    elif not isinstance(requirement_data, dict):
        requirement_data = {}
        manual_review.append("Job experience requirements are malformed.")
        malformed_requirements = True

    thresholds = {}
    for key in ("minimum_years", "maximum_years"):
        if key not in requirement_data:
            continue

        value = requirement_data[key]
        try:
            if isinstance(value, bool):
                raise ValueError
            years = float(value)
            if years < 0 or years != years or years == float("inf"):
                raise ValueError
            thresholds[key] = years
        except (TypeError, ValueError):
            invalid_threshold = True
            manual_review.append(
                "Job has an invalid " + key + " experience requirement."
            )

    has_unparsed_employment_dates = any(
        entry["date_status"] != "PARSED"
        for entry in employment_entries
        if entry["employment_type"] != "INTERNSHIP"
    )
    has_experience_data = bool(employment_entries)

    minimum_years = thresholds.get("minimum_years")
    maximum_years = thresholds.get("maximum_years")
    employment_entries_for_relevance = [
        entry for entry in employment_entries
        if entry["employment_type"] != "INTERNSHIP"
    ]
    # Only non-internship roles determine whether the job's employment
    # experience requirement can be evaluated. Internship uncertainty is
    # reported separately and must not block this calculation.
    relevance_is_uncertain = any(
        entry["relevant"] is None
        for entry in employment_entries_for_relevance
    )
    all_employment_proven_unrelated = (
        bool(employment_entries_for_relevance)
        and all(
            entry["relevant"] is False
            for entry in employment_entries_for_relevance
        )
    )
    applicable_employment_months = (
        relevant_employment_months
        if relevant_employment_entries
        else 0
        if explicitly_fresher
        or all_employment_proven_unrelated
        else None
    )
    evaluation_needs_review = (
        invalid_threshold
        or malformed_requirements
        or relevance_is_uncertain
    )

    if (
        minimum_years is not None
        and maximum_years is not None
        and minimum_years > maximum_years
    ):
        evaluation_needs_review = True
        manual_review.append(
            "The minimum experience requirement exceeds the maximum "
            "preferred experience boundary."
        )

    if (minimum_years is not None or maximum_years is not None):
        if not has_experience_data and not explicitly_fresher:
            evaluation_needs_review = True
            manual_review.append(
                "Experience requirements cannot be evaluated because "
                "candidate experience information is missing."
            )
        elif has_unparsed_employment_dates:
            evaluation_needs_review = True
            manual_review.append(
                "Experience requirements cannot be evaluated until all "
                "non-internship employment dates are verified."
            )
        elif applicable_employment_months is None:
            evaluation_needs_review = True
            manual_review.append(
                "Experience requirements cannot be evaluated until "
                "employment relevance is verified."
            )
        elif (
            minimum_years is not None
            and maximum_years is not None
            and minimum_years > maximum_years
        ):
            pass
        else:
            if minimum_years is not None:
                minimum_requirement = (
                    "Minimum experience: "
                    + _format_experience_years(minimum_years)
                    + " years of relevant non-internship employment ("
                    + str(applicable_employment_months)
                    + " relevant employment months available; "
                    + str(employment_months)
                    + " total non-internship employment months)"
                )
                if evaluation_needs_review:
                    manual_review.append(
                        minimum_requirement
                        + " cannot be evaluated until the review issues "
                        "above are resolved."
                    )
                elif applicable_employment_months >= minimum_years * 12:
                    matched_requirements.append(minimum_requirement)
                else:
                    missing_requirements.append(minimum_requirement)

            if maximum_years is not None:
                maximum_requirement = (
                    "Maximum experience: "
                    + _format_experience_years(maximum_years)
                    + " years of relevant non-internship employment ("
                    + str(applicable_employment_months)
                    + " relevant employment months available; "
                    + str(employment_months)
                    + " total non-internship employment months)"
                )
                if evaluation_needs_review:
                    manual_review.append(
                        maximum_requirement
                        + " cannot be evaluated until the review issues "
                        "above are resolved."
                    )
                elif applicable_employment_months <= maximum_years * 12:
                    matched_requirements.append(maximum_requirement)
                else:
                    missing_requirements.append(maximum_requirement)

    if malformed_requirements or invalid_threshold:
        status = "MANUAL_REVIEW"
    elif not thresholds:
        status = "NOT_SPECIFIED"
    elif evaluation_needs_review:
        status = "MANUAL_REVIEW"
    elif (
        maximum_years is not None
        and applicable_employment_months > maximum_years * 12
    ):
        status = "ABOVE_MAXIMUM"
    elif (
        minimum_years is not None
        and applicable_employment_months < minimum_years * 12
    ):
        status = "BELOW_MINIMUM"
    else:
        status = "WITHIN_RANGE"

    preferred_range_status = (
        status if maximum_years is not None else "NOT_SPECIFIED"
    )

    public_entries = []
    for entry in employment_entries:
        public_entries.append({
            key: value
            for key, value in entry.items()
            if not key.startswith("_")
        })

    return {
        "total_experience_months": total_months,
        "total_experience_years": round(total_months / 12, 2),
        "combined_experience_months": total_months,
        "combined_experience_years": round(total_months / 12, 2),
        "employment_experience_months": employment_months,
        "total_employment_experience_months": employment_months,
        "internship_experience_months": internship_months,
        "relevant_employment_experience_months": relevant_employment_months,
        "relevant_experience_months": relevant_months,
        "employment_entries": public_entries,
        "matched_requirements": matched_requirements,
        "missing_requirements": missing_requirements,
        "minimum_experience_years": minimum_years,
        "maximum_experience_years": maximum_years,
        "preferred_range_status": preferred_range_status,
        "manual_review": manual_review,
        "status": status,
    }


# ==================================
# PROJECT PATHS
# ==================================

BASE_DIR = Path(__file__).resolve().parent

CANDIDATE_FILE = (
    BASE_DIR / "analyzed_data" / "all_profiles.json"
)

JOB_DIR = BASE_DIR / "job_descriptions"


# ==================================
# LOAD CANDIDATES
# ==================================

def load_candidates():

    with open(
        CANDIDATE_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        candidates = json.load(file)

    return candidates


# ==================================
# LOAD JOB DESCRIPTIONS
# ==================================

def load_jobs():

    jobs = []

    for file_path in JOB_DIR.glob("*.json"):

        with open(
            file_path,
            "r",
            encoding="utf-8"
        ) as file:

            job = json.load(file)

            jobs.append(job)

    return jobs


# ==================================
# MAIN FUNCTION
# ==================================

def main():

    candidates = load_candidates()

    jobs = load_jobs()

    print("========== MATCHING ENGINE ==========")

    print("Total Candidates:", len(candidates))

    print("Total Jobs:", len(jobs))

    for job in jobs:

        print("\nJob:", job["job_title"])

    print("\nData Loading Successful!")

    # Test first candidate against first job

    candidate = candidates[0]

    job = jobs[0]

    result = match_skills(
        candidate.get("skills", []),
        job
    )

    print("\n========== SKILL MATCHING ==========")

    print("Candidate:", candidate["candidate_id"])

    print("Job:", job["job_title"])

    print("\nMatched Required Skills:")

    for skill in result["matched_required"]:
        print("+", skill)

    print("\nMissing Required Skills:")

    for skill in result["missing_required"]:
        print("-", skill)

    print("\nMatched Preferred Skills:")

    for skill in result["matched_preferred"]:
        print("+", skill)

    print("\nMissing Preferred Skills:")

    for skill in result["missing_preferred"]:
        print("-", skill)


    # Education Matching Test

    for education_job in jobs:
        education_result = match_education(
            candidate.get("education", []),
            education_job
        )

        print("\n========== EDUCATION MATCHING ==========")

        print("Candidate:", candidate["candidate_id"])
        print("Job:", education_job["job_title"])
        print("Status:", education_result["status"])

        print("\nMatched Education:")

        for item in education_result["matched"]:
            print("+", item)

        print("\nMissing Education:")

        for item in education_result["missing"]:
            print("-", item)

        print("\nEducation Manual Review:")

        for item in education_result["manual_review"]:
            print("?", item)

        print("\nEducation Evidence:")

        for item in education_result["evidence"]:
            print("*", item)

    # Experience Matching Test

    for experience_job in jobs:
        experience_result = match_experience(
            candidate,
            experience_job
        )

        print("\n========== EXPERIENCE MATCHING ==========")
        print("Candidate:", candidate["candidate_id"])
        print("Job:", experience_job["job_title"])
        print("Status:", experience_result["status"])
        print(
            "Combined experience (unique months):",
            experience_result["combined_experience_months"],
            "months (",
            experience_result["combined_experience_years"],
            "years )"
        )
        print(
            "Month counting: elapsed calendar months "
            "(start month included, end month excluded)."
        )
        print(
            "Combined duration merges overlapping periods; employment "
            "and internship totals are shown separately."
        )
        print(
            "Experience calculated as of:",
            date.today().strftime("%B %Y")
        )
        print(
            "Non-internship employment:",
            experience_result["employment_experience_months"],
            "months"
        )
        print(
            "Internship experience (reported separately):",
            experience_result["internship_experience_months"],
            "months"
        )
        print(
            "Relevant experience supported by evidence:",
            experience_result["relevant_experience_months"],
            "months"
        )
        print(
            "Relevant non-internship employment:",
            experience_result["relevant_employment_experience_months"],
            "months"
        )

        print("\nEmployment Entries:")
        for entry in experience_result["employment_entries"]:
            print(
                "-",
                entry["employment_type"],
                "|",
                entry["date_status"],
                "|",
                entry["duration_months"],
                "months"
            )
            if entry["start_date"] is not None:
                print(
                    "  Date range:",
                    entry["start_date"],
                    "to",
                    entry["end_date"]
                )
            print("  Original:", entry["original_text"])
            print("  Relevant:", entry["relevant"])
            print("  Relevance status:", entry["relevance_status"])
            if entry["relevance_terms"]:
                print(
                    "  Relevance evidence terms:",
                    ", ".join(entry["relevance_terms"])
                )
            print("  Evidence:")
            for evidence_item in entry["evidence"]:
                print("   *", evidence_item)

        print("\nMatched Experience Requirements:")
        for item in experience_result["matched_requirements"]:
            print("+", item)

        print("\nMissing Experience Requirements:")
        for item in experience_result["missing_requirements"]:
            print("-", item)

        if experience_result["maximum_experience_years"] is not None:
            print(
                "\nMaximum experience (preferred upper boundary):",
                _format_experience_years(
                    experience_result["maximum_experience_years"]
                ),
                "years"
            )
            if experience_result["status"] == "ABOVE_MAXIMUM":
                print(
                    "Candidate is above the preferred range; "
                    "this is not an automatic rejection."
                )

        print("\nExperience Manual Review:")
        for item in experience_result["manual_review"]:
            print("?", item)

if __name__ == "__main__":

    main()
