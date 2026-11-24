from io import BytesIO

import pytest
from docx import Document

import resume_upload


class FakeUpload:
    def __init__(self, name, data):
        self.name = name
        self._data = data

    def getvalue(self):
        return self._data


def make_docx_bytes(text=""):
    stream = BytesIO()
    document = Document()
    if text:
        for line in text.split("\n"):
            document.add_paragraph(line)
    document.save(stream)
    stream.seek(0)
    return stream.getvalue()


@pytest.fixture
def synthetic_job():
    return {
        "job_id": "JD-SYNTH-001",
        "job_title": "Synthetic Python Developer",
        "required_skills": ["Python", "SQL"],
        "preferred_skills": ["Docker"],
        "software_tools": ["Git"],
        "education": ["Computer Science"],
        "experience": {"minimum_years": 1, "maximum_years": 5, "minimum_projects": 1},
    }


def test_valid_docx_analyzes(synthetic_job):
    text = """SKILLS
Python, SQL, Docker
EDUCATION
Bachelor of Computer Science
EXPERIMENT
PROJECTS
Python Data Tool
Built a Python SQL reporting tool.
EXPERIENCE
Synthetic Engineer 2024 - 2026
"""
    upload = FakeUpload("synthetic.docx", make_docx_bytes(text))
    result = resume_upload.analyze_upload(upload, synthetic_job)
    assert result["profile"]["candidate_id"].startswith("UPL-")
    assert "Python" in result["profile"]["skills"]
    assert result["quality"]["validation_status"] in {"VALID", "REVIEW_REQUIRED", "INVALID"}
    assert result["score"]["overall_score"] is not None or result["score"]["score_coverage"] >= 0


def test_empty_docx_rejected():
    upload = FakeUpload("empty.docx", make_docx_bytes())
    with pytest.raises(resume_upload.UploadValidationError, match="no readable text"):
        resume_upload.analyze_upload(upload, {"job_id": "JD", "job_title": "Test"})


def test_corrupt_docx_rejected():
    upload = FakeUpload("corrupt.docx", b"not a zip/docx")
    with pytest.raises(resume_upload.UploadValidationError, match="corrupt"):
        resume_upload.analyze_upload(upload, {"job_id": "JD", "job_title": "Test"})


def test_wrong_extension_rejected():
    upload = FakeUpload("resume.pdf", b"pdf bytes")
    with pytest.raises(resume_upload.UploadValidationError, match="docx"):
        resume_upload.validate_uploaded_docx(upload)


def test_oversized_upload_rejected():
    upload = FakeUpload("large.docx", b"x" * (resume_upload.MAX_UPLOAD_BYTES + 1))
    with pytest.raises(resume_upload.UploadValidationError, match="5 MB"):
        resume_upload.validate_uploaded_docx(upload)


def test_missing_resume_sections_are_reviewable(synthetic_job):
    upload = FakeUpload("minimal.docx", make_docx_bytes("Candidate synthetic document"))
    result = resume_upload.analyze_upload(upload, synthetic_job)
    assert result["profile"]["skills"] == []
    assert result["quality"]["validation_status"] in {"REVIEW_REQUIRED", "INVALID"}


def test_tuple_profile_normalization_or_review():
    profile = {
        "skills": ("Python", "SQL"),
        "education": ("Computer Science",),
        "experience": ("Engineer 2024",),
        "experience_evidence": ("2024",),
        "projects": ({"title": "Synthetic"},),
        "certifications": (),
        "professional_summary": (),
        "awards": (),
    }
    adapted = resume_upload.adapt_v2_profile(profile, "UPL-SYNTH")
    assert adapted["skills"] == ["Python", "SQL"]
    assert adapted["projects"] == [{"title": "Synthetic"}]


def test_malformed_tuple_is_preserved_for_review():
    profile = {"skills": ("Python", 123)}
    adapted = resume_upload.adapt_v2_profile(profile, "UPL-SYNTH")
    assert adapted["skills"] == ("Python", 123)
    assert any("manual review" in reason.lower() for reason in adapted["manual_review"])


def test_job_selection_loads_synthetic_safe_json():
    jobs = resume_upload.load_job_descriptions()
    assert jobs
    assert all(job.get("job_id") for job in jobs)


def test_matching_and_scoring_contract(synthetic_job):
    profile = {
        "candidate_id": "UPL-SYNTH",
        "source_file": "Uploaded resume",
        "skills": ["Python", "SQL"],
        "education": ["Bachelor of Computer Science"],
        "experience": ["Synthetic Engineer 2024 - Present"],
        "experience_evidence": ["Synthetic Engineer 2024 - Present"],
        "projects": ["Synthetic Python Tool", "Built a Python SQL reporting tool"],
        "certifications": [],
        "manual_review": [],
        "verification_required": True,
    }
    quality = resume_upload.data_quality_validator.validate_candidate(profile)
    project = resume_upload.project_matcher.match_candidate_projects(profile, synthetic_job)
    score = resume_upload.scoring_engine.evaluate_candidate_job(profile, synthetic_job, project, quality)
    assert score["manual_review_required"] is True
    assert 0 <= (score["score_coverage"] or 0) <= 100


def test_download_payload_excludes_raw_data(synthetic_job):
    profile = {
        "candidate_id": "UPL-SYNTH",
        "source_file": "Uploaded resume",
        "skills": ["Python"],
        "education": ["Computer Science"],
        "experience": ["Synthetic Engineer"],
        "experience_evidence": [],
        "projects": ["Synthetic Tool"],
        "certifications": [],
        "manual_review": [],
        "verification_required": True,
    }
    quality = resume_upload.data_quality_validator.validate_candidate(profile)
    skill_match = resume_upload.resume_job_matcher.match_skills(profile["skills"], synthetic_job)
    education_match = resume_upload.resume_job_matcher.match_education(profile["education"], synthetic_job)
    experience_match = resume_upload.resume_job_matcher.match_experience(profile, synthetic_job)
    project_match = resume_upload.project_matcher.match_candidate_projects(profile, synthetic_job)
    score = resume_upload.scoring_engine.evaluate_candidate_job(profile, synthetic_job, project_match, quality)
    result = {
        "processing_id": "UPL-SYNTH",
        "profile": profile,
        "extracted_text": "PRIVATE RAW TEXT",
        "quality": quality,
        "skill_match": skill_match,
        "education_match": education_match,
        "experience_match": experience_match,
        "project_match": project_match,
        "score": score,
    }
    payload = resume_upload.build_download_payload(result)
    serialized = str(payload)
    assert "PRIVATE RAW TEXT" not in serialized
    assert "Uploaded resume" in serialized


def test_education_matching_manual_review(synthetic_job):
    matched = resume_upload.resume_job_matcher.match_education(
        ["Bachelor of Computer Science"], synthetic_job
    )
    assert "Computer Science" in matched["matched"]

    review_job = dict(synthetic_job)
    review_job["education"] = ["Related or Relevant Domain"]
    reviewed = resume_upload.resume_job_matcher.match_education(
        ["Bachelor of Data Science"], review_job
    )
    assert reviewed["manual_review"]


def test_experience_manual_review(synthetic_job):
    profile = {
        "candidate_id": "UPL-SYNTH",
        "skills": [],
        "education": [],
        "experience": ["Synthetic Engineer"],
        "experience_evidence": [],
    }
    result = resume_upload.resume_job_matcher.match_experience(profile, synthetic_job)
    assert result["status"] == "MANUAL_REVIEW"
    assert result["manual_review"]


def test_project_matching(synthetic_job):
    profile = {
        "candidate_id": "UPL-SYNTH",
        "source_file": "Uploaded resume",
        "projects": ["Synthetic Python SQL Tool", "Built a reporting tool using Python"],
    }
    result = resume_upload.project_matcher.match_candidate_projects(profile, synthetic_job)
    assert result["status"] in {"BELOW_MINIMUM_PROJECT_COUNT", "PARTIAL_MATCH", "MATCHED"}
    assert isinstance(result["project_count"], int)
    assert result["grouping_note"]


def test_sanitized_csv_and_json_exports(synthetic_job):
    profile = {
        "candidate_id": "UPL-SYNTH",
        "source_file": "Uploaded resume",
        "skills": ["Python"],
        "education": ["Computer Science"],
        "experience": ["Engineer 2024 - Present"],
        "experience_evidence": [],
        "projects": ["Synthetic Tool"],
        "certifications": [],
        "manual_review": [],
        "verification_required": True,
    }
    quality = resume_upload.data_quality_validator.validate_candidate(profile)
    skill_match = resume_upload.resume_job_matcher.match_skills(profile["skills"], synthetic_job)
    education_match = resume_upload.resume_job_matcher.match_education(profile["education"], synthetic_job)
    experience_match = resume_upload.resume_job_matcher.match_experience(profile, synthetic_job)
    project_match = resume_upload.project_matcher.match_candidate_projects(profile, synthetic_job)
    score = resume_upload.scoring_engine.evaluate_candidate_job(profile, synthetic_job, project_match, quality)
    result = {
        "processing_id": "UPL-SYNTH",
        "profile": profile,
        "extracted_text": "RAW PRIVATE TEXT",
        "quality": quality,
        "skill_match": skill_match,
        "education_match": education_match,
        "experience_match": experience_match,
        "project_match": project_match,
        "score": score,
    }
    csv_bytes = resume_upload.build_csv_payload(result)
    json_payload = resume_upload.build_download_payload(result)
    assert b"processing_id" in csv_bytes
    assert b"RAW PRIVATE TEXT" not in csv_bytes
    assert "RAW PRIVATE TEXT" not in str(json_payload)


def test_demo_mode_app_smoke():
    from pathlib import Path
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
    app.run(timeout=20)
    assert not app.exception
    modes = app.radio(key="runtime_mode")
    assert "Demo Mode" in modes.options
    assert modes.value == "Demo Mode"


def test_resume_analysis_app_smoke():
    from pathlib import Path
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
    app.run(timeout=20)
    app.radio(key="runtime_mode").set_value("Resume Analysis")
    app.run(timeout=20)
    assert not app.exception
    assert app.file_uploader(key="resume_upload") is not None


def test_existing_local_and_demo_regression():
    from pathlib import Path
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
    app.run(timeout=20)

    for mode in ("Existing Local Reports", "Demo Mode"):
        app.radio(key="runtime_mode").set_value(mode)
        app.run(timeout=20)
        assert not app.exception


def test_all_dashboard_pages_app_smoke():
    from pathlib import Path
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
    app.run(timeout=20)
    assert not app.exception

    for page_name in (
        "Executive Dashboard",
        "Candidate Ranking",
        "Candidate Profile",
        "Analytics",
        "Data Quality",
        "Reports",
    ):
        app.radio(key="active_page").set_value(page_name)
        app.run(timeout=20)
        assert not app.exception


def test_clear_analysis_session_state():
    state = {
        "analysis_uploaded_file": "synthetic.docx",
        "analysis_extracted_text": "raw",
        "analysis_profile": {},
        "analysis_score": {},
        "analysis_download_payload": {},
        "unrelated": "keep",
    }
    resume_upload.clear_analysis_session(state)
    assert "analysis_uploaded_file" not in state
    assert "analysis_extracted_text" not in state
    assert state["unrelated"] == "keep"
