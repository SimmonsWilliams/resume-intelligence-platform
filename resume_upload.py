"""Session-only orchestration for uploaded resume analysis.

This module contains no persistent storage. It reuses the existing matcher,
validator, project, and scoring implementations rather than duplicating their logic.
"""

from io import BytesIO
from pathlib import Path
import csv
import json
import re
from uuid import uuid4

from docx import Document

import data_quality_validator
import project_matcher
import resume_analyzer_v2
import resume_job_matcher
import scoring_engine


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ANALYSIS_SESSION_KEYS = (
    "analysis_uploaded_file",
    "analysis_extracted_text",
    "analysis_profile",
    "analysis_quality",
    "analysis_skill_match",
    "analysis_education_match",
    "analysis_experience_match",
    "analysis_project_match",
    "analysis_score",
    "analysis_download_payload",
)


class UploadValidationError(ValueError):
    """Raised when an upload is not safe or usable for analysis."""


def validate_uploaded_docx(uploaded_file):
    """Validate an uploaded Streamlit file without writing it to disk."""
    if uploaded_file is None:
        raise UploadValidationError("No resume file was selected.")

    name = getattr(uploaded_file, "name", "")
    if not isinstance(name, str) or not name.lower().endswith(".docx"):
        raise UploadValidationError("Only .docx resume files are accepted.")

    get_value = getattr(uploaded_file, "getvalue", None)
    if not callable(get_value):
        raise UploadValidationError("The uploaded file could not be read.")

    data = get_value()
    if not isinstance(data, (bytes, bytearray)):
        raise UploadValidationError("The uploaded file is not readable as bytes.")
    data = bytes(data)

    if not data:
        raise UploadValidationError("The uploaded DOCX is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadValidationError("The uploaded DOCX exceeds the 5 MB limit.")

    return data


def extract_docx_bytes(data):
    """Extract paragraph and table text from DOCX bytes in memory."""
    stream = BytesIO(data)
    stream.seek(0)
    try:
        document = Document(stream)
    except Exception as exc:
        raise UploadValidationError("The uploaded file is corrupt or is not a valid DOCX") from exc

    content = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            content.append(text)

    for table in document.tables:
        for row in table.rows:
            row_text = []
            for cell in row.cells:
                text = cell.text.strip()
                if text:
                    row_text.append(text)
            if row_text:
                content.append(" | ".join(row_text))

    text = "\n".join(content).strip()
    if not text:
        raise UploadValidationError("The uploaded DOCX contains no readable text.")
    return text


def adapt_v2_profile(profile, processing_id):
    """Create a scoring-compatible in-memory profile and normalize tuple fields."""
    adapted = dict(profile)
    adapted["candidate_id"] = processing_id
    adapted["source_file"] = "Uploaded resume"

    list_fields = (
        "skills",
        "education",
        "experience",
        "experience_evidence",
        "projects",
        "certifications",
        "professional_summary",
        "awards",
    )
    adapted.setdefault("manual_review", [])

    for field in list_fields:
        value = adapted.get(field)
        if isinstance(value, tuple):
            if field in {"skills", "education", "experience", "experience_evidence"}:
                if all(isinstance(item, str) for item in value):
                    adapted[field] = list(value)
                else:
                    adapted[field] = value
                    adapted["manual_review"].append(
                        f"Adapter validation failed for tuple value in {field}; manual review required."
                    )
            elif all(isinstance(item, dict) for item in value):
                adapted[field] = list(value)
            else:
                adapted[field] = value
                adapted["manual_review"].append(
                    f"Adapter validation failed for tuple value in {field}; manual review required."
                )
        elif not isinstance(value, list):
            adapted[field] = []

    adapted.setdefault("verification_required", True)
    adapted.setdefault("extraction_status", "ANALYZED")
    return adapted


def load_job_descriptions(base_dir=None):
    base_dir = Path(base_dir or Path(__file__).resolve().parent)
    job_dir = base_dir / "job_descriptions"
    jobs = []
    if not job_dir.is_dir():
        return jobs
    for path in sorted(job_dir.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as file:
                job = json.load(file)
            if isinstance(job, dict) and str(job.get("job_id", "")).strip():
                jobs.append(job)
        except (OSError, json.JSONDecodeError):
            continue
    return jobs


def analyze_upload(uploaded_file, job):
    """Validate, extract, analyze, match, and score one uploaded resume."""
    data = validate_uploaded_docx(uploaded_file)
    text = extract_docx_bytes(data)

    processing_id = f"UPL-{uuid4().hex[:8].upper()}"
    ontology = resume_analyzer_v2.load_ontology()
    patterns = resume_analyzer_v2.compile_skill_patterns(ontology)
    transient_candidate = {
        "candidate_id": processing_id,
        "source_file": "Uploaded resume",
        "full_text": text,
        "character_count": len(text),
        "extraction_status": "SUCCESS",
    }
    raw_profile = resume_analyzer_v2.analyze_candidate(transient_candidate, patterns)
    profile = adapt_v2_profile(raw_profile, processing_id)

    quality = data_quality_validator.validate_candidate(profile)
    skill_match = resume_job_matcher.match_skills(profile.get("skills", []), job)
    education_match = resume_job_matcher.match_education(profile.get("education", []), job)
    experience_match = resume_job_matcher.match_experience(profile, job)
    project_match = project_matcher.match_candidate_projects(profile, job)
    score = scoring_engine.evaluate_candidate_job(profile, job, project_match, quality)

    return {
        "processing_id": processing_id,
        "profile": profile,
        "extracted_text": text,
        "quality": quality,
        "skill_match": skill_match,
        "education_match": education_match,
        "experience_match": experience_match,
        "project_match": project_match,
        "score": score,
    }


def build_download_payload(result):
    """Build a sanitized payload that excludes raw text and personal evidence."""
    profile = result["profile"]
    score = result["score"]
    quality = result["quality"]
    skill_match = result["skill_match"]
    education_match = result["education_match"]
    experience_match = result["experience_match"]
    project_match = result["project_match"]

    return {
        "processing_id": result["processing_id"],
        "mode": "resume_analysis",
        "profile": {
            "candidate_id": result["processing_id"],
            "source_label": "Uploaded resume",
            "skills": list(profile.get("skills", [])),
            "education_status": education_match,
            "experience_status": {
                "status": experience_match.get("status"),
                "manual_review": experience_match.get("manual_review", []),
            },
            "project_status": {
                "status": project_match.get("status"),
                "project_count": project_match.get("project_count"),
            },
            "verification_required": True,
        },
        "quality": {
            "validation_status": quality.get("validation_status"),
            "issue_count": quality.get("issue_count"),
            "warning_count": quality.get("warning_count"),
            "issues": quality.get("issues", []),
            "warnings": quality.get("warnings", []),
            "missing_optional_sections": quality.get("missing_optional_sections", []),
        },
        "skill_match": {
            "matched_required": skill_match.get("matched_required", []),
            "missing_required": skill_match.get("missing_required", []),
            "matched_preferred": skill_match.get("matched_preferred", []),
            "missing_preferred": skill_match.get("missing_preferred", []),
        },
        "project_match": {
            "status": project_match.get("status"),
            "project_count": project_match.get("project_count"),
            "missing_required_skills": project_match.get("missing_required_skills", []),
        },
        "scoring": {
            "overall_score": score.get("overall_score"),
            "score_coverage": score.get("score_coverage"),
            "evaluation_status": score.get("evaluation_status"),
            "manual_review_required": score.get("manual_review_required"),
            "manual_review_reasons": score.get("manual_review_reasons", []),
            "component_coverage": score.get("component_coverage", {}),
            "required_skills_score": score.get("required_skills_score"),
            "preferred_skills_score": score.get("preferred_skills_score"),
            "education_score": score.get("education_score"),
            "experience_score": score.get("experience_score"),
            "project_score": score.get("project_score"),
        },
        "privacy": {
            "original_filename_excluded": True,
            "raw_text_excluded": True,
            "raw_evidence_excluded": True,
        },
    }


def build_csv_payload(result):
    payload = build_download_payload(result)
    row = {
        "processing_id": payload["processing_id"],
        "mode": payload["mode"],
        "matched_required_skills": " | ".join(payload["skill_match"]["matched_required"]),
        "missing_required_skills": " | ".join(payload["skill_match"]["missing_required"]),
        "education_status": payload["profile"]["education_status"].get("status", ""),
        "experience_status": payload["profile"]["experience_status"].get("status", ""),
        "project_status": payload["project_match"]["status"],
        "quality_status": payload["quality"]["validation_status"],
        "quality_issues": " | ".join(payload["quality"]["issues"]),
        "quality_warnings": " | ".join(payload["quality"]["warnings"]),
        "overall_score": payload["scoring"]["overall_score"],
        "score_coverage": payload["scoring"]["score_coverage"],
        "evaluation_status": payload["scoring"]["evaluation_status"],
        "manual_review_required": payload["scoring"]["manual_review_required"],
        "manual_review_reasons": " | ".join(payload["scoring"]["manual_review_reasons"]),
    }
    from io import StringIO
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    return output.getvalue().encode("utf-8")


def clear_analysis_session(session_state):
    """Remove application references to analysis values from session state."""
    for key in ANALYSIS_SESSION_KEYS:
        session_state.pop(key, None)
    session_state.pop("resume_upload", None)
    session_state.pop("resume_analysis_job_id", None)
    session_state.pop("analysis_upload_selection", None)
