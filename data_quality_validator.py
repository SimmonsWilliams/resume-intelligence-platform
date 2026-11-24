
import json
import csv
import re

from pathlib import Path
from collections import Counter


# ==========================================
# 1. PROJECT PATH CONFIGURATION
# ==========================================

BASE_DIR = Path(__file__).resolve().parent

INPUT_FILE = (
    BASE_DIR / "analyzed_data" / "all_profiles.json"
)

REPORT_DIR = BASE_DIR / "reports"

REPORT_DIR.mkdir(parents=True, exist_ok=True)


# ==========================================
# 2. VALIDATION CONFIGURATION
# ==========================================

LIST_FIELDS = [
    "skills",
    "education",
    "experience",
    "projects",
    "certifications",
    "professional_summary",
    "awards"
]

REQUIRED_FIELDS = [
    "candidate_id",
    "source_file"
]


# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================

def is_empty(value):
    """Check whether a value is empty."""

    return (
        value is None
        or (isinstance(value, str) and not value.strip())
        or (isinstance(value, (list, dict)) and len(value) == 0)
    )


def find_duplicates(values):
    """Find duplicate text values without case sensitivity."""

    normalized = [
        value.strip().casefold()
        for value in values
        if isinstance(value, str) and value.strip()
    ]

    counts = Counter(normalized)

    return [
        item
        for item, count in counts.items()
        if count > 1
    ]


# ==========================================
# 4. CANDIDATE VALIDATION
# ==========================================


def validate_candidate(candidate):

    issues = []
    warnings = []
    missing_sections = []

    candidate_id = candidate.get(
        "candidate_id", "UNKNOWN"
    )

    # 1. Check required fields
    for field in REQUIRED_FIELDS:

        if is_empty(candidate.get(field)):
            issues.append(
                f"Missing required field: {field}"
            )

    # 2. Check important and optional sections
    important_fields = [
        "skills",
        "education",
        "experience"
    ]

    optional_fields = [
        "projects",
        "certifications",
        "professional_summary",
        "awards"
    ]

    # Important fields
    for field in important_fields:

        value = candidate.get(field)

        if field not in candidate:
            issues.append(f"Missing field: {field}")
            continue

        if not isinstance(value, list):
            issues.append(
                f"Invalid data type: {field} must be a list"
            )
            continue

        if not value:
            warnings.append(
                f"Missing important information: {field}"
            )

    # Optional fields
    for field in optional_fields:

        value = candidate.get(field)

        if field not in candidate:
            missing_sections.append(field)
            continue

        if not isinstance(value, list):
            issues.append(
                f"Invalid data type: {field} must be a list"
            )
            continue

        if not value:
            missing_sections.append(field)

    # 3. Check empty entries
    for field in LIST_FIELDS:

        value = candidate.get(field)

        if not isinstance(value, list):
            continue

        empty_items = [
            item for item in value
            if not isinstance(item, str)
            or not item.strip()
        ]

        if empty_items:
            issues.append(
                f"Empty or invalid entries in {field}"
            )

    # 4. Check duplicate skills
    skills = candidate.get("skills", [])

    if isinstance(skills, list):

        duplicates = find_duplicates(skills)

        if duplicates:
            warnings.append(
                f"Duplicate skills: {', '.join(duplicates)}"
            )

    # 5. Check experience date evidence
    experience = candidate.get("experience", [])

    if isinstance(experience, list) and experience:

        dated_entries = [
            item for item in experience
            if isinstance(item, str)
            and re.search(r"\b(?:19|20)\d{2}\b", item)
        ]

        if not dated_entries:
            warnings.append(
                "Experience dates could not be identified"
            )

    # 6. Determine validation status
    if issues:
        status = "INVALID"

    elif warnings:
        status = "REVIEW_REQUIRED"

    else:
        status = "VALID"

    return {
        "candidate_id": candidate_id,
        "source_file": candidate.get("source_file", ""),
        "validation_status": status,
        "issue_count": len(issues),
        "warning_count": len(warnings),
        "issues": issues,
        "warnings": warnings,
        "missing_optional_sections": missing_sections
    }


    issues = []
    warnings = []

    candidate_id = candidate.get(
        "candidate_id", "UNKNOWN"
    )

    # Check required fields
    for field in REQUIRED_FIELDS:

        if is_empty(candidate.get(field)):

            issues.append(
                f"Missing required field: {field}"
            )

    # Check list fields
    for field in LIST_FIELDS:

        value = candidate.get(field)

        if field not in candidate:

            issues.append(
                f"Missing field: {field}"
            )

            continue

        if not isinstance(value, list):

            issues.append(
                f"Invalid data type: {field} must be a list"
            )

            continue

        # Empty sections are warnings
        if len(value) == 0:

            warnings.append(
                f"No information found in {field}"
            )

        # Check empty elements
        empty_items = [
            item for item in value
            if not isinstance(item, str)
            or not item.strip()
        ]

        if empty_items:

            issues.append(
                f"Empty or invalid entries in {field}"
            )

        # Check duplicate entries
        if field == "skills":

            duplicates = find_duplicates(value)

            if duplicates:

                warnings.append(
                    f"Duplicate skills: {', '.join(duplicates)}"
                )

    # Check experience evidence
    experience = candidate.get("experience", [])

    if isinstance(experience, list):

        dated_entries = [
            item for item in experience
            if isinstance(item, str)
            and re.search(r"\b(?:19|20)\d{2}\b", item)
        ]

        if experience and not dated_entries:

            warnings.append(
                "Experience dates could not be identified"
            )

    # Determine validation status
    if issues:

        status = "INVALID"

    elif warnings:

        status = "REVIEW_REQUIRED"

    else:

        status = "VALID"

    return {
        "candidate_id": candidate_id,
        "source_file": candidate.get("source_file", ""),
        "validation_status": status,
        "issue_count": len(issues),
        "warning_count": len(warnings),
        "issues": issues,
        "warnings": warnings
    }


# ==========================================
# 5. VALIDATE ALL CANDIDATES
# ==========================================

def validate_all_candidates():

    if not INPUT_FILE.exists():

        print("ERROR: Input JSON file not found!")

        return

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        candidates = json.load(file)

    if not isinstance(candidates, list):

        print("ERROR: Expected a list of candidates!")

        return

    results = []
    candidate_ids = []

    for candidate in candidates:

        if not isinstance(candidate, dict):

            print("ERROR: Invalid candidate record!")
            continue

        result = validate_candidate(candidate)

        results.append(result)

        candidate_ids.append(
            candidate.get("candidate_id")
        )

        print(
            f"[{result['validation_status']}] "
            f"{result['candidate_id']} | "
            f"Issues: {result['issue_count']} | "
            f"Warnings: {result['warning_count']}"
        )

    # Check duplicate candidate IDs
    valid_ids = [
        item for item in candidate_ids
        if isinstance(item, str) and item.strip()
    ]

    duplicate_ids = find_duplicates(valid_ids)

    # Save detailed JSON report
    json_report = REPORT_DIR / "quality_report.json"

    with open(
        json_report,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            results,
            file,
            indent=4,
            ensure_ascii=False
        )

    # Save CSV report
    csv_report = REPORT_DIR / "quality_report.csv"

    with open(
        csv_report,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        writer = csv.writer(file)

        writer.writerow([
            "Candidate ID",
            "Source File",
            "Status",
            "Issue Count",
            "Warning Count",
            "Issues",
            "Warnings"
        ])

        for result in results:

            writer.writerow([
                result["candidate_id"],
                result["source_file"],
                result["validation_status"],
                result["issue_count"],
                result["warning_count"],
                " | ".join(result["issues"]),
                " | ".join(result["warnings"])
            ])

    # Calculate summary
    status_counts = Counter(
        result["validation_status"]
        for result in results
    )

    total_issues = sum(
        result["issue_count"]
        for result in results
    )

    total_warnings = sum(
        result["warning_count"]
        for result in results
    )

    print("\n========== QUALITY SUMMARY ==========")

    print(f"Total Candidates: {len(candidates)}")

    print(f"Valid: {status_counts['VALID']}")

    print(
        f"Review Required: "
        f"{status_counts['REVIEW_REQUIRED']}"
    )

    print(f"Invalid: {status_counts['INVALID']}")

    print(f"Total Issues: {total_issues}")

    print(f"Total Warnings: {total_warnings}")

    print(f"Duplicate Candidate IDs: {duplicate_ids}")

    print("\nReports Generated:")

    print("reports/quality_report.json")

    print("reports/quality_report.csv")

    print("=====================================")


# ==========================================
# 6. MAIN METHOD
# ==========================================

if __name__ == "__main__":

    validate_all_candidates()
