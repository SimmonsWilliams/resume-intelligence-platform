import html
import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from resume_upload import (
    UploadValidationError,
    analyze_upload,
    build_csv_payload,
    build_download_payload,
    clear_analysis_session,
    load_job_descriptions,
)


BASE_DIR = Path(__file__).resolve().parent
REPORT_DIR = BASE_DIR / "reports"
PROFILE_PATH = BASE_DIR / "analyzed_data" / "all_profiles.json"

REPORT_FILES = {
    "Final Scoring": "final_scoring_report.csv",
    "Candidate Ranking": "candidate_ranking.csv",
    "Data Quality": "quality_report.csv",
    "Project Matching": "project_match_report.csv",
    "Resume Analysis": "analysis_report.csv",
}

COLORS = {
    "navy": "#0B1120",
    "sidebar": "#111827",
    "card": "#172033",
    "accent": "#6366F1",
    "cyan": "#22D3EE",
    "success": "#10B981",
    "warning": "#F59E0B",
    "error": "#EF4444",
    "muted": "#94A3B8",
    "text": "#E5E7EB",
}

st.set_page_config(
    page_title="Talent Intelligence | Recruitment Dashboard",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(show_spinner=False)
def load_report(filename):
    path = REPORT_DIR / filename
    if not path.is_file():
        return pd.DataFrame(), f"Report file not found: {path.name}"
    try:
        return pd.read_csv(path), None
    except (OSError, UnicodeDecodeError, pd.errors.ParserError, ValueError) as exc:
        return pd.DataFrame(), f"Could not read {path.name}: {exc}"


@st.cache_data(show_spinner=False)
def load_json_file(path_string):
    path = Path(path_string)
    if not path.is_file():
        return None, f"Data file not found: {path.name}"
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file), None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"Could not read {path.name}: {exc}"


def column_name(frame, *candidates):
    lookup = {str(name).strip().lower(): name for name in frame.columns}
    for candidate in candidates:
        found = lookup.get(candidate.strip().lower())
        if found is not None:
            return found
    return None


def values_for(frame, *candidates):
    name = column_name(frame, *candidates)
    if name is None:
        return pd.Series(index=frame.index, dtype="object")
    return frame[name]


def as_numeric(series):
    return pd.to_numeric(series, errors="coerce")


def is_true(series):
    return series.map(
        lambda value: value is True
        or (isinstance(value, (int, float)) and value == 1)
        or (isinstance(value, str) and value.strip().lower() in {"true", "yes", "1"})
    )


def quality_status_counts(frame):
    status = values_for(frame, "Status", "validation_status").fillna("").astype(str).str.upper()
    invalid = status.str.contains("INVALID|ERROR", regex=True)
    review = status.str.contains("REVIEW|WARNING", regex=True) & ~invalid
    valid = status.str.contains("VALID", regex=True) & ~invalid & ~review
    return {
        "Valid": int(valid.sum()),
        "Review required": int(review.sum()),
        "Invalid": int(invalid.sum()),
    }


def score_frame(frame):
    score_col = column_name(frame, "overall_score")
    if score_col is None:
        return pd.Series(index=frame.index, dtype="float64")
    return as_numeric(frame[score_col])


def chart_layout(fig, height=360):
    fig.update_layout(
        height=height,
        autosize=True,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, sans-serif", "color": COLORS["muted"], "size": 12},
        margin={"l": 36, "r": 24, "t": 28, "b": 76},
        legend={
            "bgcolor": "rgba(0,0,0,0)",
            "orientation": "h",
            "yanchor": "top",
            "y": -0.2,
            "xanchor": "center",
            "x": 0.5,
        },
        xaxis={
            "gridcolor": "rgba(148,163,184,0.12)",
            "zerolinecolor": "rgba(148,163,184,0.12)",
            "automargin": True,
        },
        yaxis={
            "gridcolor": "rgba(148,163,184,0.12)",
            "zerolinecolor": "rgba(148,163,184,0.12)",
            "automargin": True,
        },
    )
    return fig


def show_empty(message):
    st.info(message, icon="ℹ️")


def show_table(frame, empty_message="No records are available for this view."):
    if frame.empty:
        show_empty(empty_message)
    else:
        st.dataframe(frame, width="stretch", height=480, hide_index=True)


def csv_download(frame, filename, label):
    st.download_button(
        label=label,
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
        width="stretch",
    )


def job_options(frame):
    id_col = column_name(frame, "job_id")
    title_col = column_name(frame, "job_title")
    if id_col is None:
        return []
    jobs = frame[[id_col] + ([title_col] if title_col else [])].dropna(subset=[id_col]).drop_duplicates()
    options = []
    for _, row in jobs.iterrows():
        job_id = str(row[id_col])
        title = str(row[title_col]) if title_col and pd.notna(row[title_col]) else job_id
        options.append((job_id, f"{title} · {job_id}"))
    return options


def filtered_by_job(frame, job_id):
    id_col = column_name(frame, "job_id")
    if id_col is None or job_id is None:
        return frame.copy()
    return frame[frame[id_col].astype(str) == str(job_id)].copy()


def selected_evaluation(frame, candidate_id, job_id):
    candidate_col = column_name(frame, "candidate_id", "Candidate ID")
    job_col = column_name(frame, "job_id")
    if candidate_col is None:
        return None
    selected = frame[frame[candidate_col].astype(str) == str(candidate_id)]
    if job_col is not None and job_id is not None:
        selected = selected[selected[job_col].astype(str) == str(job_id)]
    return None if selected.empty else selected.iloc[0].to_dict()


def find_json_record(records, candidate_id, job_id=None):
    if not isinstance(records, list):
        return None
    for record in records:
        if not isinstance(record, dict) or str(record.get("candidate_id", "")) != str(candidate_id):
            continue
        if job_id is None or str(record.get("job_id", "")) == str(job_id):
            return record
    return None


def render_candidate_profile(
    candidate_id,
    job_id,
    profiles,
    scoring_df,
    project_records,
    scoring_records,
    quality_df,
):
    profile = find_json_record(profiles, candidate_id)
    if profile is None:
        show_empty(f"No analyzed profile was found for {candidate_id}.")
        return

    score = selected_evaluation(scoring_df, candidate_id, job_id)
    project = find_json_record(project_records, candidate_id, job_id)
    quality_col = column_name(quality_df, "Candidate ID", "candidate_id")
    quality_rows = (
        quality_df[quality_df[quality_col].astype(str) == str(candidate_id)]
        if quality_col is not None
        else pd.DataFrame()
    )
    quality = quality_rows.iloc[0].to_dict() if not quality_rows.empty else {}
    score_detail = find_json_record(scoring_records, candidate_id, job_id) or {}

    st.markdown(f"## {html.escape(str(candidate_id))}")
    source = profile.get("source_file")
    st.caption(f"Source resume: {source if source else 'Not provided in analyzed profile'}")

    if score:
        overall = score.get("overall_score")
        coverage = score.get("score_coverage")
        kpi_cols = st.columns(3)
        with kpi_cols[0]:
            st.metric("Overall match score", f"{float(overall):.1f}%" if pd.notna(overall) else "Unavailable")
        with kpi_cols[1]:
            st.metric("Score coverage", f"{float(coverage):.1f}%" if pd.notna(coverage) else "Unavailable")
        with kpi_cols[2]:
            st.metric("Evaluation status", str(score.get("evaluation_status") or "Unavailable"))
        st.caption("Match score reflects scored evidence; coverage reflects the weighted evidence available.")
    else:
        show_empty("No scoring record is available for this candidate and job.")

    left, right = st.columns(2)
    with left:
        st.subheader("Skills")
        skills = profile.get("skills") or []
        if skills:
            st.write(" · ".join(str(item) for item in skills))
        else:
            show_empty("No extracted skills are present in this profile.")

        st.subheader("Required skill matching")
        matched = project.get("matched_required_skills", []) if project else []
        missing = project.get("missing_required_skills", []) if project else []
        if project is None:
            show_empty("No project matching record is available for this evaluation.")
        else:
            st.markdown(f"**Matched in project report** · {', '.join(map(str, matched)) or 'None reported'}")
            st.markdown(f"**Missing in project report** · {', '.join(map(str, missing)) or 'None reported'}")

        st.subheader("Education")
        education = profile.get("education") or []
        if education:
            for entry in education:
                st.markdown(f"- {entry}")
        else:
            show_empty("No education entries are present in this profile.")
        if score:
            education_score = score.get("education_score")
            education_coverage = (score_detail.get("component_coverage") or {}).get("education_score")
            st.caption(
                f"Education score: {float(education_score):.1f} points"
                if pd.notna(education_score)
                else "Education score: unavailable"
            )
            if education_coverage is not None:
                st.caption(f"Education evidence coverage: {education_coverage}%")

    with right:
        st.subheader("Preferred skill matching")
        matched = project.get("matched_preferred_skills", []) if project else []
        missing = project.get("missing_preferred_skills", []) if project else []
        if project is None:
            show_empty("No project matching record is available for this evaluation.")
        else:
            st.markdown(f"**Matched in project report** · {', '.join(map(str, matched)) or 'None reported'}")
            st.markdown(f"**Missing in project report** · {', '.join(map(str, missing)) or 'None reported'}")

        st.subheader("Employment & internship experience")
        experience = profile.get("experience") or []
        if experience:
            for entry in experience:
                st.markdown(f"- {entry}")
        else:
            show_empty("No experience entries are present in this profile.")

        st.subheader("Relevant experience evidence")
        evidence = profile.get("experience_evidence") or []
        if evidence:
            for entry in evidence:
                st.markdown(f"- {entry}")
        else:
            show_empty("No separate experience evidence is present in this profile.")

    st.subheader("Project matching")
    if project:
        project_count = project.get("project_count")
        project_status = project.get("status", "Unavailable")
        st.markdown(f"**Status:** {project_status} · **Projects reported:** {project_count if project_count is not None else 'Unavailable'}")
        for item in project.get("projects") or []:
            title = item.get("title") or "Project"
            with st.expander(str(title)):
                for line in item.get("description_lines") or []:
                    st.markdown(f"- {line}")
        if project.get("grouping_note"):
            st.caption(str(project["grouping_note"]))
        st.markdown(f"**Missing requirements:** {', '.join(map(str, project.get('missing_required_skills') or [])) or 'None reported'}")
    else:
        show_empty("No project matching details are available for this evaluation.")

    st.subheader("Manual review")
    review_required = bool(score and is_true(pd.Series([score.get("manual_review_required")])).iloc[0])
    reasons = score_detail.get("manual_review_reasons") or []
    quality_status = quality.get(column_name(quality_df, "Status", "validation_status") or "")
    warnings = quality.get(column_name(quality_df, "Warnings", "warnings") or "")
    issues = quality.get(column_name(quality_df, "Issues", "issues") or "")
    if review_required:
        st.warning("Manual review is required for this evaluation; no hiring decision is implied.")
    else:
        st.info("No manual-review requirement is recorded for this evaluation.")
    for reason in reasons:
        st.markdown(f"- {reason}")
    if quality_status:
        st.markdown(f"**Data quality status:** {quality_status}")
    for label, raw in (("Quality warnings", warnings), ("Quality issues", issues)):
        if raw is not None and not (isinstance(raw, float) and pd.isna(raw)) and str(raw).strip():
            st.markdown(f"**{label}:** {raw}")


def apply_styles():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        :root { color-scheme: dark; }
        html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
        .stApp { background: #0B1120; color: #E5E7EB; }
        [data-testid="stAppViewContainer"] { background: #0B1120; }
        [data-testid="stHeader"] { background: rgba(11,17,32,.88); }
        [data-testid="stSidebar"] { background: #111827; border-right: 1px solid rgba(148,163,184,.12); }
        [data-testid="stSidebar"] > div:first-child { background: #111827; }
        [data-testid="stMetric"] {
            background: #172033; border: 1px solid rgba(148,163,184,.14);
            min-height: 112px; box-sizing: border-box; display: flex;
            flex-direction: column; justify-content: center; gap: 8px;
            padding: 16px 18px; border-radius: 16px;
            box-shadow: 0 12px 30px rgba(0,0,0,.12); transition: transform .18s ease, border-color .18s ease;
        }
        [data-testid="stMetric"]:hover { transform: translateY(-2px); border-color: rgba(99,102,241,.55); }
        [data-testid="stMetricLabel"] {
            color: #94A3B8; min-height: 2.4em; white-space: normal;
            overflow-wrap: anywhere; line-height: 1.2;
        }
        [data-testid="stMetricValue"] {
            color: #F8FAFC; white-space: normal; overflow-wrap: anywhere;
            word-break: normal; line-height: 1.15;
            font-size: clamp(1.05rem, 1.35vw, 1.45rem);
        }
        [data-testid="stMetricValue"] > div {
            white-space: normal; overflow-wrap: anywhere;
        }
        [data-testid="stPlotlyChart"], [data-testid="stDataFrame"] {
            background: #172033; border: 1px solid rgba(148,163,184,.12);
            border-radius: 16px; padding: 4px;
        }
        h1, h2, h3 { letter-spacing: -.035em; }
        h1 { font-weight: 800; margin-bottom: .35rem; }
        h2 { font-weight: 700; margin-top: 1.8rem; margin-bottom: .75rem; }
        h3 { font-weight: 700; margin-top: 1.35rem; margin-bottom: .65rem; }
        .stMarkdown p, .stMarkdown li { overflow-wrap: anywhere; }
        [data-testid="stCaptionContainer"] { color: #94A3B8; }
        [data-testid="stButton"] button, [data-testid="stDownloadButton"] button {
            border-radius: 10px; border: 1px solid rgba(99,102,241,.45);
            background: rgba(99,102,241,.14); color: #E5E7EB; transition: all .18s ease;
        }
        [data-testid="stButton"] button:hover, [data-testid="stDownloadButton"] button:hover {
            background: #6366F1; border-color: #6366F1; color: white;
        }
        [data-testid="stSelectbox"], [data-testid="stTextInput"], [data-testid="stSlider"] { color: #E5E7EB; }
        hr { border-color: rgba(148,163,184,.14); }
        </style>
        """,
        unsafe_allow_html=True,
    )


def open_selected_profile():
    selected = st.session_state.get("ranking_candidate_detail")
    if selected:
        candidate_id, job_id = selected.split("|", 1)
        st.session_state["profile_candidate_id"] = candidate_id
        st.session_state["profile_job_id"] = job_id
        st.session_state["active_page"] = "Candidate Profile"


def build_demo_data():
    """Return clearly fictional records for the portfolio demonstration."""
    scoring = pd.DataFrame([
        {
            "candidate_id": "DEMO-001", "job_id": "JOB-JAVA",
            "job_title": "Junior Java Developer", "overall_score": 86.0,
            "score_coverage": 92.0, "manual_review_required": False,
            "evaluation_status": "EVALUATED", "required_skills_score": 23,
            "preferred_skills_score": 8, "education_score": 13,
            "experience_score": 21, "projects_score": 21,
        },
        {
            "candidate_id": "DEMO-002", "job_id": "JOB-JAVA",
            "job_title": "Junior Java Developer", "overall_score": 72.0,
            "score_coverage": 84.0, "manual_review_required": True,
            "evaluation_status": "MANUAL_REVIEW", "required_skills_score": 20,
            "preferred_skills_score": 7, "education_score": 12,
            "experience_score": 16, "projects_score": 17,
        },
        {
            "candidate_id": "DEMO-003", "job_id": "JOB-PYTHON",
            "job_title": "Python Developer", "overall_score": 79.0,
            "score_coverage": 88.0, "manual_review_required": False,
            "evaluation_status": "EVALUATED", "required_skills_score": 22,
            "preferred_skills_score": 8, "education_score": 12,
            "experience_score": 18, "projects_score": 19,
        },
    ])

    ranking = scoring.copy()
    ranking.insert(0, "ranking", [1, 2, 1])

    quality = pd.DataFrame([
        {"candidate_id": "DEMO-001", "Status": "VALID",
         "Issues": "", "Warnings": ""},
        {"candidate_id": "DEMO-002", "Status": "REVIEW_REQUIRED",
         "Issues": "", "Warnings": "Experience evidence needs manual review"},
        {"candidate_id": "DEMO-003", "Status": "VALID",
         "Issues": "", "Warnings": ""},
    ])

    projects = pd.DataFrame([
        {"candidate_id": "DEMO-001", "job_id": "JOB-JAVA",
         "status": "MATCHED", "project_name": "Inventory API"},
        {"candidate_id": "DEMO-002", "job_id": "JOB-JAVA",
         "status": "PARTIAL_MATCH", "project_name": "Student Management App"},
        {"candidate_id": "DEMO-003", "job_id": "JOB-PYTHON",
         "status": "MATCHED", "project_name": "Data Processing Tool"},
    ])

    analysis = pd.DataFrame([
        {"candidate_id": "DEMO-001", "job_id": "JOB-JAVA",
         "job_title": "Junior Java Developer",
         "skills": "Java, Spring Boot, SQL",
         "experience": "Fictional demonstration experience",
         "education": "Demo qualification",
         "projects": "Inventory API"},
        {"candidate_id": "DEMO-002", "job_id": "JOB-JAVA",
         "job_title": "Junior Java Developer",
         "skills": "Java, MySQL, REST APIs",
         "experience": "Fictional demonstration experience",
         "education": "Demo qualification",
         "projects": "Student Management App"},
        {"candidate_id": "DEMO-003", "job_id": "JOB-PYTHON",
         "job_title": "Python Developer",
         "skills": "Python, Pandas, SQL",
         "experience": "Fictional demonstration experience",
         "education": "Demo qualification",
         "projects": "Data Processing Tool"},
    ])

    return {
        "Final Scoring": scoring,
        "Candidate Ranking": ranking,
        "Data Quality": quality,
        "Project Matching": projects,
        "Resume Analysis": analysis,
    }



apply_styles()

data_mode = st.sidebar.radio(
    "Runtime mode",
    ["Existing Local Reports", "Demo Mode", "Resume Analysis"],
    index=1,
    key="runtime_mode",
)

if data_mode == "Demo Mode":
    reports = build_demo_data()
    report_errors = {}
    profiles = {}
    profiles_error = None
    project_records = []
    scoring_records = []
    project_json_error = None
    scoring_json_error = None

elif data_mode == "Resume Analysis":
    # Stage 3: placeholder only. No upload or resume processing.
    reports = {label: pd.DataFrame() for label in REPORT_FILES}
    report_errors = {}
    profiles = {}
    profiles_error = None
    project_records = []
    scoring_records = []
    project_json_error = None
    scoring_json_error = None

else:
    reports = {}
    report_errors = {}
    for report_label, filename in REPORT_FILES.items():
        reports[report_label], report_errors[report_label] = load_report(filename)

    profiles, profiles_error = load_json_file(str(PROFILE_PATH))
    project_json, project_json_error = load_json_file(
        str(REPORT_DIR / "project_match_report.json")
    )
    scoring_json, scoring_json_error = load_json_file(
        str(REPORT_DIR / "final_scoring_report.json")
    )

    project_records = project_json if isinstance(project_json, list) else (
        project_json.get("records", []) if isinstance(project_json, dict) else []
    )
    scoring_records = (
        scoring_json.get("records", []) if isinstance(scoring_json, dict) else []
    )

scoring_df = reports["Final Scoring"]
ranking_df = reports["Candidate Ranking"]
quality_df = reports["Data Quality"]
project_df = reports["Project Matching"]
analysis_df = reports["Resume Analysis"]


with st.sidebar:
    st.markdown("## ◈  Talent Intelligence")
    st.caption("RECRUITMENT OPERATIONS")
    st.divider()
    page = st.radio(
        "Workspace",
        [
            "Executive Dashboard",
            "Candidate Ranking",
            "Candidate Profile",
            "Analytics",
            "Data Quality",
            "Reports",
        ],
        key="active_page",
        label_visibility="collapsed",
    )
    st.divider()
    candidate_count = values_for(scoring_df, "candidate_id").nunique()
    st.caption(f"◉  {candidate_count} candidates in scoring data")
    st.caption("Human review remains part of every decision.")

st.markdown("# Recruitment Intelligence")
st.markdown(
    f"<span style='color:{COLORS['muted']}'>Talent operations overview"
    " &nbsp;·&nbsp; Evidence-led candidate evaluation</span>",
    unsafe_allow_html=True,
)
st.divider()

for label, error in report_errors.items():
    if error:
        st.warning(error, icon="⚠️")
if profiles_error:
    st.warning(profiles_error, icon="⚠️")
if project_json_error:
    st.warning(f"Detailed project evidence is unavailable: {project_json_error}", icon="⚠️")
if scoring_json_error:
    st.warning(f"Detailed scoring notes are unavailable: {scoring_json_error}", icon="⚠️")


if data_mode == "Resume Analysis":
    st.subheader("Resume Analysis")
    st.warning(
        "Human verification is mandatory. Scores are decision-support indicators, "
        "not hiring decisions or automated rejections.",
        icon="⚠️",
    )
    st.caption(
        "Use a synthetic or permitted resume only. Uploaded content is held temporarily "
        "in Streamlit session state and is not guaranteed secure private storage."
    )

    jobs = load_job_descriptions(BASE_DIR)
    if not jobs:
        st.error("No valid job descriptions are available.")
    else:
        job_labels = {
            str(job["job_id"]): f"{job.get('job_title') or 'Untitled'} · {job['job_id']}"
            for job in jobs
        }
        selected_job_id = st.selectbox(
            "Select job",
            list(job_labels),
            format_func=lambda value: job_labels[value],
            key="resume_analysis_job_id",
        )
        selected_job = next(job for job in jobs if str(job["job_id"]) == selected_job_id)

        uploaded = st.file_uploader(
            "Upload DOCX resume",
            type=["docx"],
            accept_multiple_files=False,
            key="resume_upload",
        )

        if uploaded is not None:
            previous_selection = st.session_state.get("analysis_upload_selection")
            current_selection = (getattr(uploaded, "name", ""), str(selected_job_id))
            if previous_selection != current_selection:
                for key in (
                    "analysis_extracted_text", "analysis_profile", "analysis_quality",
                    "analysis_skill_match", "analysis_education_match",
                    "analysis_experience_match", "analysis_project_match",
                    "analysis_score", "analysis_download_payload",
                ):
                    st.session_state.pop(key, None)

                try:
                    result = analyze_upload(uploaded, selected_job)
                    st.session_state["analysis_uploaded_file"] = getattr(uploaded, "name", "")
                    st.session_state["analysis_upload_selection"] = current_selection
                    st.session_state["analysis_extracted_text"] = result["extracted_text"]
                    st.session_state["analysis_profile"] = result["profile"]
                    st.session_state["analysis_quality"] = result["quality"]
                    st.session_state["analysis_skill_match"] = result["skill_match"]
                    st.session_state["analysis_education_match"] = result["education_match"]
                    st.session_state["analysis_experience_match"] = result["experience_match"]
                    st.session_state["analysis_project_match"] = result["project_match"]
                    st.session_state["analysis_score"] = result["score"]
                    st.session_state["analysis_download_payload"] = build_download_payload(result)
                except UploadValidationError as exc:
                    st.session_state.pop("analysis_profile", None)
                    st.error(str(exc))
                except Exception:
                    st.session_state.pop("analysis_profile", None)
                    st.error("The resume could not be analyzed safely. Please review the file and try again.")

        if st.session_state.get("analysis_profile"):
            profile = st.session_state["analysis_profile"]
            quality = st.session_state["analysis_quality"]
            skill_match = st.session_state["analysis_skill_match"]
            education_match = st.session_state["analysis_education_match"]
            experience_match = st.session_state["analysis_experience_match"]
            project_match = st.session_state["analysis_project_match"]
            score = st.session_state["analysis_score"]

            st.subheader("Extracted candidate profile")
            left, right = st.columns(2)
            with left:
                st.markdown("**Skills**")
                skills = profile.get("skills", [])
                st.write(" · ".join(map(str, skills)) if skills else "No skills extracted")

                st.markdown("**Education**")
                education = profile.get("education", [])
                if education:
                    for entry in education:
                        st.markdown(f"- {entry}")
                else:
                    st.info("No education section was extracted.")

                st.markdown("**Projects**")
                projects = profile.get("projects", [])
                if projects:
                    for entry in projects:
                        st.markdown(f"- {entry}")
                else:
                    st.info("No project section was extracted.")

            with right:
                st.markdown("**Experience**")
                experience = profile.get("experience", [])
                if experience:
                    for entry in experience:
                        st.markdown(f"- {entry}")
                else:
                    st.info("No experience section was extracted.")

                st.markdown("**Certifications**")
                certifications = profile.get("certifications", [])
                st.write(" · ".join(map(str, certifications)) if certifications else "No certifications extracted")

                st.markdown("**Professional summary**")
                summary = profile.get("professional_summary", [])
                if summary:
                    for entry in summary:
                        st.markdown(f"- {entry}")
                else:
                    st.info("No professional summary was extracted.")

            st.subheader("Evidence and verification")
            evidence = profile.get("skill_evidence", [])
            if evidence:
                for item in evidence:
                    st.markdown(
                        f"**{item.get('skill')}** — {item.get('confidence')} confidence; "
                        f"verification required: {item.get('verification_required', True)}"
                    )
                    for line in item.get("evidence", [])[:3]:
                        st.caption(line)
            else:
                st.info("No skill evidence was extracted.")

            unknown = profile.get("potential_skill_candidates", [])
            if unknown:
                st.markdown("**Pending unknown skill suggestions**")
                for item in unknown:
                    st.markdown(f"- {item.get('candidate_term')} (pending review)")

            st.subheader("Data quality")
            st.markdown(f"**Status:** {quality.get('validation_status', 'UNAVAILABLE')}")
            if quality.get("issues"):
                st.markdown("**Issues**")
                for issue in quality["issues"]:
                    st.markdown(f"- {issue}")
            if quality.get("warnings"):
                st.markdown("**Warnings**")
                for warning in quality["warnings"]:
                    st.markdown(f"- {warning}")
            if quality.get("missing_optional_sections"):
                st.markdown("**Missing optional sections:** " + ", ".join(quality["missing_optional_sections"]))

            st.subheader("Job matching")
            match_left, match_right = st.columns(2)
            with match_left:
                st.markdown("**Skills**")
                st.markdown("Matched required: " + (", ".join(skill_match["matched_required"]) or "None"))
                st.markdown("Missing required: " + (", ".join(skill_match["missing_required"]) or "None"))
                st.markdown("Matched preferred: " + (", ".join(skill_match["matched_preferred"]) or "None"))
                st.markdown("Missing preferred: " + (", ".join(skill_match["missing_preferred"]) or "None"))

                st.markdown("**Education**")
                st.markdown(f"Status: {education_match.get('status', 'UNAVAILABLE')}")
                st.markdown("Matched: " + (", ".join(education_match.get("matched", [])) or "None"))
                st.markdown("Missing: " + (", ".join(education_match.get("missing", [])) or "None"))
                if education_match.get("manual_review"):
                    st.markdown("Manual review: " + ", ".join(education_match["manual_review"]))

            with match_right:
                st.markdown("**Experience**")
                st.markdown(f"Status: {experience_match.get('status', 'UNAVAILABLE')}")
                if experience_match.get("manual_review"):
                    for reason in experience_match["manual_review"]:
                        st.markdown(f"- {reason}")
                else:
                    st.markdown("No experience manual-review issue reported.")

                st.markdown("**Projects**")
                st.markdown(f"Status: {project_match.get('status', 'UNAVAILABLE')}")
                st.markdown(f"Projects identified: {project_match.get('project_count', 0)}")
                st.markdown("Missing required project skills: " + (", ".join(project_match.get("missing_required_skills", [])) or "None"))
                if project_match.get("grouping_note"):
                    st.caption(project_match["grouping_note"])

            st.subheader("Scoring breakdown")
            metric_columns = st.columns(5)
            component_fields = (
                ("required_skills_score", "Required skills"),
                ("preferred_skills_score", "Preferred skills"),
                ("education_score", "Education"),
                ("experience_score", "Experience"),
                ("project_score", "Projects"),
            )
            for column, (field, label) in zip(metric_columns, component_fields):
                value = score.get(field)
                column.metric(label, "Unavailable" if value is None else f"{float(value):.1f}")

            overall = score.get("overall_score")
            st.metric(
                "Overall decision-support score",
                "Unavailable" if overall is None else f"{float(overall):.1f}%",
            )
            st.markdown(f"**Score coverage:** {float(score.get('score_coverage', 0.0)):.1f}%")
            st.markdown(f"**Evaluation status:** {score.get('evaluation_status', 'UNAVAILABLE')}")

            if score.get("manual_review_reasons"):
                st.warning("Manual review is required before any human use of this result.")
                for reason in score["manual_review_reasons"]:
                    st.markdown(f"- {reason}")

            st.subheader("Sanitized downloads")
            csv_payload = st.session_state.get("analysis_download_payload")
            if csv_payload:
                st.download_button(
                    "Download CSV",
                    data=build_csv_payload({
                        "processing_id": profile["candidate_id"],
                        "profile": profile,
                        "quality": quality,
                        "skill_match": skill_match,
                        "education_match": education_match,
                        "experience_match": experience_match,
                        "project_match": project_match,
                        "score": score,
                    }),
                    file_name=f"{profile['candidate_id']}_analysis.csv",
                    mime="text/csv",
                )
                st.download_button(
                    "Download JSON",
                    data=json.dumps(csv_payload, ensure_ascii=False, indent=2).encode("utf-8"),
                    file_name=f"{profile['candidate_id']}_analysis.json",
                    mime="application/json",
                )

    if st.button("Clear Analysis", key="clear_resume_analysis"):
        clear_analysis_session(st.session_state)
        st.success("Application references to the analysis were cleared from session state.")
        st.caption("This does not guarantee secure deletion from server process memory.")
        st.rerun()

elif page == "Executive Dashboard":
    st.subheader("Executive overview")
    scores = score_frame(scoring_df)
    candidate_ids = values_for(scoring_df, "candidate_id").dropna().astype(str)
    jobs = job_options(scoring_df)
    manual = is_true(values_for(scoring_df, "manual_review_required"))
    metrics = st.columns(5)
    metrics[0].metric("Total candidates", f"{candidate_ids.nunique():,}")
    metrics[1].metric("Total jobs", f"{len(jobs):,}")
    metrics[2].metric("Evaluations", f"{len(scoring_df):,}")
    metrics[3].metric("Average match score", f"{scores.mean():.1f}%" if scores.notna().any() else "Unavailable")
    metrics[4].metric("Manual reviews", f"{int(manual.sum()):,}" if not scoring_df.empty else "0")
    st.caption("Candidate and evaluation totals are derived from scoring report rows. Missing scores are excluded from averages.")

    chart_left, chart_right = st.columns([1.2, 1])
    with chart_left:
        st.markdown("### Score distribution")
        score_data = scoring_df.copy()
        score_data["Match score"] = score_frame(score_data)
        score_data = score_data.dropna(subset=["Match score"])
        if score_data.empty:
            show_empty("No overall scores are available to chart.")
        else:
            fig = px.histogram(
                score_data,
                x="Match score",
                color_discrete_sequence=[COLORS["accent"]],
                nbins=16,
                labels={"Match score": "Overall match score"},
            )
            fig.update_traces(marker_line_color="#A5B4FC", marker_line_width=1, opacity=0.88)
            st.plotly_chart(chart_layout(fig), width="stretch", config={"displayModeBar": False, "responsive": True})
    with chart_right:
        st.markdown("### Candidate quality status")
        status_counts = quality_status_counts(quality_df)
        donut_data = pd.DataFrame(
            [{"Status": key, "Candidates": value} for key, value in status_counts.items() if value]
        )
        if donut_data.empty:
            show_empty("No quality status values are available.")
        else:
            fig = px.pie(
                donut_data,
                names="Status",
                values="Candidates",
                hole=0.72,
                color="Status",
                color_discrete_map={
                    "Valid": COLORS["success"],
                    "Review required": COLORS["warning"],
                    "Invalid": COLORS["error"],
                },
            )
            fig.update_traces(textinfo="percent", marker={"line": {"color": COLORS["card"], "width": 3}})
            st.plotly_chart(chart_layout(fig), width="stretch", config={"displayModeBar": False, "responsive": True})

    chart_left, chart_right = st.columns([1.15, 1])
    with chart_left:
        st.markdown("### Job-wise score comparison")
        plot_data = scoring_df.copy()
        title_col = column_name(plot_data, "job_title")
        if title_col is not None:
            plot_data["Job"] = plot_data[title_col].fillna("Unknown job").astype(str)
            plot_data["Match score"] = score_frame(plot_data)
            plot_data = plot_data.dropna(subset=["Match score"])
        if title_col is None or plot_data.empty:
            show_empty("Job title or score data is unavailable.")
        else:
            fig = px.box(
                plot_data,
                x="Job",
                y="Match score",
                color="Job",
                color_discrete_sequence=[COLORS["accent"], COLORS["cyan"]],
                points="outliers",
            )
            fig.update_layout(showlegend=False)
            fig.update_xaxes(tickangle=-25, automargin=True)
            st.plotly_chart(chart_layout(fig), width="stretch", config={"displayModeBar": False, "responsive": True})
    with chart_right:
        st.markdown("### Top candidate evaluations")
        display = ranking_df.copy()
        rank_score = score_frame(display)
        display["overall_score"] = rank_score
        display = display.dropna(subset=["overall_score"]).sort_values("overall_score", ascending=False).head(10)
        wanted = [
            column_name(display, "ranking"),
            column_name(display, "candidate_id"),
            column_name(display, "job_title"),
            column_name(display, "overall_score"),
            column_name(display, "score_coverage"),
            column_name(display, "evaluation_status"),
        ]
        wanted = [col for col in wanted if col]
        if display.empty:
            show_empty("No scored candidate evaluations are available.")
        else:
            st.dataframe(display[wanted], width="stretch", hide_index=True)
            st.caption("Sorted by reported match score; rank and review status remain as reported.")

    st.divider()
    st.markdown("### Data quality overview")
    quality_counts = quality_status_counts(quality_df)
    q_cols = st.columns(3)
    for container, (label, value), color in zip(
        q_cols,
        quality_counts.items(),
        [COLORS["success"], COLORS["warning"], COLORS["error"]],
    ):
        with container:
            st.markdown(f"<div style='color:{color};font-size:13px;font-weight:600'>{label}</div>", unsafe_allow_html=True)
            st.metric(label, value)


elif page == "Candidate Ranking":
    st.subheader("Candidate ranking")
    options = job_options(ranking_df)
    if not options:
        show_empty("Job selection is unavailable because the ranking report has no job_id column.")
    else:
        labels = {job_id: label for job_id, label in options}
        job_id = st.selectbox("Select job", list(labels), format_func=lambda value: labels[value], key="ranking_job")
        job_frame = filtered_by_job(ranking_df, job_id)
        rank_col = column_name(job_frame, "ranking")
        candidate_col = column_name(job_frame, "candidate_id")
        score_col = column_name(job_frame, "overall_score")

        controls = st.columns([1.2, 1, 1])
        with controls[0]:
            query = st.text_input("Search candidate ID", placeholder="e.g. CAND-014", key="ranking_search")
        scores = as_numeric(job_frame[score_col]) if score_col else pd.Series(index=job_frame.index, dtype="float64")
        available_scores = scores.dropna()
        with controls[1]:
            max_score = float(max(100, available_scores.max())) if not available_scores.empty else 100.0
            minimum = st.slider("Minimum match score", 0.0, max_score, 0.0, 1.0, key="ranking_min_score")
        with controls[2]:
            order = st.selectbox("Sort by overall score", ["Highest first", "Lowest first"], key="ranking_sort")

        filtered = job_frame.copy()
        if candidate_col and query.strip():
            filtered = filtered[filtered[candidate_col].astype(str).str.contains(query.strip(), case=False, na=False)]
        if score_col:
            filtered = filtered[as_numeric(filtered[score_col]).notna() & (as_numeric(filtered[score_col]) >= minimum)]
            filtered[score_col] = as_numeric(filtered[score_col])
            filtered = filtered.sort_values(score_col, ascending=order == "Lowest first", na_position="last")
        elif minimum > 0:
            filtered = filtered.iloc[0:0]
        st.caption(f"{len(filtered)} evaluations match the selected filters. Unavailable scores are excluded from score filtering.")

        display_columns = [
            column_name(filtered, "ranking"),
            column_name(filtered, "candidate_id"),
            column_name(filtered, "overall_score"),
            column_name(filtered, "score_coverage"),
            column_name(filtered, "manual_review_required"),
            column_name(filtered, "evaluation_status"),
        ]
        display_columns = [name for name in display_columns if name]
        if filtered.empty:
            show_empty("No candidates match these filters.")
        else:
            st.dataframe(
                filtered[display_columns],
                width="stretch",
                hide_index=True,
                column_config={
                    "overall_score": st.column_config.ProgressColumn(
                        "Match score", min_value=0, max_value=100, format="%.1f"
                    ),
                    "score_coverage": st.column_config.ProgressColumn(
                        "Score coverage", min_value=0, max_value=100, format="%.1f"
                    ),
                },
            )

        st.markdown("### Candidate detail")
        if candidate_col and not filtered.empty:
            filtered_job_col = column_name(filtered, "job_id")
            candidate_options = []
            candidate_labels = {}
            for _, row in filtered.iterrows():
                candidate_id = str(row[candidate_col])
                row_job = str(row[filtered_job_col]) if filtered_job_col else str(job_id)
                key = f"{candidate_id}|{row_job}"
                candidate_options.append(key)
                candidate_labels[key] = f"{candidate_id} · {labels.get(row_job, row_job)}"
            selected = st.selectbox(
                "Choose an evaluation",
                candidate_options,
                format_func=lambda value: candidate_labels[value],
                key="ranking_candidate_detail",
            )
            st.button(
                "Open candidate profile",
                key="open_ranked_profile",
                on_click=open_selected_profile,
            )


elif page == "Candidate Profile":
    st.subheader("Candidate profile")
    options = job_options(scoring_df)
    if not options:
        show_empty("Candidate profiles require job and scoring data.")
    else:
        labels = {job_id: label for job_id, label in options}
        saved_job = st.session_state.get("profile_job_id")
        default_job_index = list(labels).index(saved_job) if saved_job in labels else 0
        job_id = st.selectbox(
            "Select job",
            list(labels),
            index=default_job_index,
            format_func=lambda value: labels[value],
            key="profile_job",
        )
        evaluations = filtered_by_job(scoring_df, job_id)
        candidate_col = column_name(evaluations, "candidate_id")
        candidate_ids = sorted(evaluations[candidate_col].dropna().astype(str).unique()) if candidate_col else []
        if not candidate_ids:
            show_empty("No candidates are available for this job.")
        else:
            saved_candidate = st.session_state.get("profile_candidate_id")
            index = candidate_ids.index(saved_candidate) if saved_candidate in candidate_ids else 0
            candidate_id = st.selectbox("Candidate ID", candidate_ids, index=index, key="profile_candidate")
            st.session_state["profile_candidate_id"] = candidate_id
            st.session_state["profile_job_id"] = job_id
            if data_mode == "Demo Mode":
                st.markdown("### Fictional demonstration evaluation")
                demo_row = evaluations[
                    evaluations[candidate_col].astype(str) == str(candidate_id)
                ]
                if demo_row.empty:
                    show_empty("No demonstration evaluation is available.")
                else:
                    st.dataframe(demo_row, width="stretch", hide_index=True)
                st.caption(
                    "This is synthetic demonstration data, not a real candidate record."
                )
            else:
                render_candidate_profile(
                    candidate_id,
                    job_id,
                    profiles,
                    scoring_df,
                    project_records,
                    scoring_records,
                    quality_df,
                )


elif page == "Analytics":
    st.subheader("Recruitment analytics")
    options = job_options(scoring_df)
    job_labels = {job_id: label for job_id, label in options}
    selected_jobs = st.multiselect(
        "Filter jobs",
        list(job_labels),
        default=list(job_labels),
        format_func=lambda value: job_labels[value],
        key="analytics_jobs",
    ) if job_labels else []
    analytics_df = scoring_df.copy()
    job_col = column_name(analytics_df, "job_id")
    if job_col is not None and job_labels:
        analytics_df = analytics_df[analytics_df[job_col].astype(str).isin(selected_jobs)]

    left, right = st.columns(2)
    with left:
        st.markdown("### Overall score distribution")
        dist = analytics_df.copy()
        dist["Overall score"] = score_frame(dist)
        dist = dist.dropna(subset=["Overall score"])
        if dist.empty:
            show_empty("No overall scores are available.")
        else:
            fig = px.histogram(dist, x="Overall score", color_discrete_sequence=[COLORS["accent"]], nbins=18)
            st.plotly_chart(chart_layout(fig), width="stretch", config={"displayModeBar": False, "responsive": True})
    with right:
        st.markdown("### Job-wise score comparison")
        title_col = column_name(analytics_df, "job_title")
        compare = analytics_df.copy()
        compare["Overall score"] = score_frame(compare)
        compare = compare.dropna(subset=["Overall score"])
        if title_col is None or compare.empty:
            show_empty("Job title or overall score data is unavailable.")
        else:
            fig = px.box(compare, x=title_col, y="Overall score", color=title_col, points="outliers")
            fig.update_layout(showlegend=False)
            fig.update_xaxes(tickangle=-25, automargin=True)
            st.plotly_chart(chart_layout(fig), width="stretch", config={"displayModeBar": False, "responsive": True})

    left, right = st.columns(2)
    with left:
        st.markdown("### Required skills score")
        required_col = column_name(analytics_df, "required_skills_score")
        if required_col is None or as_numeric(analytics_df[required_col]).notna().sum() == 0:
            show_empty("Required skills scores are unavailable.")
        else:
            req = analytics_df.copy()
            req["Required skills score"] = as_numeric(req[required_col])
            by_job = column_name(req, "job_title")
            if by_job:
                req = req.dropna(subset=["Required skills score"])
                fig = px.box(req, x=by_job, y="Required skills score", color=by_job, points="outliers")
                fig.update_layout(showlegend=False)
                fig.update_xaxes(tickangle=-25, automargin=True)
            else:
                fig = px.histogram(req.dropna(subset=["Required skills score"]), x="Required skills score", color_discrete_sequence=[COLORS["cyan"]])
            st.plotly_chart(chart_layout(fig), width="stretch", config={"displayModeBar": False, "responsive": True})
    with right:
        st.markdown("### Experience score distribution")
        experience_col = column_name(analytics_df, "experience_score")
        if experience_col is None or as_numeric(analytics_df[experience_col]).notna().sum() == 0:
            show_empty("Experience scores are unavailable.")
        else:
            experience = as_numeric(analytics_df[experience_col]).dropna()
            fig = px.histogram(
                x=experience,
                nbins=16,
                color_discrete_sequence=[COLORS["cyan"]],
                labels={"x": "Experience score (points)", "count": "Evaluations"},
            )
            st.plotly_chart(chart_layout(fig), width="stretch", config={"displayModeBar": False, "responsive": True})

    left, right = st.columns(2)
    with left:
        st.markdown("### Project matching status")
        project_job_col = column_name(project_df, "job_id")
        project_status_col = column_name(project_df, "status")
        project_data = project_df.copy()
        if project_job_col is not None and selected_jobs:
            project_data = project_data[project_data[project_job_col].astype(str).isin(selected_jobs)]
        if project_status_col is None or project_data.empty:
            show_empty("Project matching status is unavailable.")
        else:
            fig = px.histogram(
                project_data,
                x=project_status_col,
                color=project_status_col,
                color_discrete_sequence=[COLORS["accent"], COLORS["cyan"], COLORS["warning"]],
            )
            fig.update_layout(showlegend=False)
            st.plotly_chart(chart_layout(fig), width="stretch", config={"displayModeBar": False, "responsive": True})
    with right:
        st.markdown("### Data quality status")
        counts = quality_status_counts(quality_df)
        chart_data = pd.DataFrame([{"Status": key, "Candidates": value} for key, value in counts.items() if value])
        if chart_data.empty:
            show_empty("Data quality status is unavailable.")
        else:
            fig = px.pie(
                chart_data,
                names="Status",
                values="Candidates",
                hole=0.65,
                color="Status",
                color_discrete_map={
                    "Valid": COLORS["success"],
                    "Review required": COLORS["warning"],
                    "Invalid": COLORS["error"],
                },
            )
            st.plotly_chart(chart_layout(fig), width="stretch", config={"displayModeBar": False, "responsive": True})
    st.caption("Score-component charts show reported score points; they are not candidate counts or evidence coverage.")


elif page == "Data Quality":
    st.subheader("Data quality")
    counts = quality_status_counts(quality_df)
    cols = st.columns(3)
    for container, label in zip(cols, ["Valid", "Review required", "Invalid"]):
        with container:
            container.metric(label, counts[label])

    if quality_df.empty:
        show_empty("The quality report is unavailable or contains no records.")
    else:
        search = st.text_input("Search quality report", placeholder="Candidate ID, source file, status, warning...", key="quality_search")
        filtered = quality_df.copy()
        if search.strip():
            mask = filtered.astype(str).apply(
                lambda column: column.str.contains(search.strip(), case=False, na=False)
            ).any(axis=1)
            filtered = filtered[mask]
        st.caption(f"{len(filtered)} of {len(quality_df)} candidates shown.")
        show_table(filtered)
        with st.expander("Detailed warnings and issues", expanded=True):
            issue_col = column_name(filtered, "Issues", "issues")
            warning_col = column_name(filtered, "Warnings", "warnings")
            candidate_col = column_name(filtered, "Candidate ID", "candidate_id")
            if issue_col is None and warning_col is None:
                show_empty("Detailed issues and warnings are not included in this report.")
            else:
                for _, row in filtered.iterrows():
                    candidate = row[candidate_col] if candidate_col else "Candidate"
                    issues = row[issue_col] if issue_col else None
                    warnings = row[warning_col] if warning_col else None
                    has_detail = (
                        (issues is not None and pd.notna(issues) and str(issues).strip())
                        or (warnings is not None and pd.notna(warnings) and str(warnings).strip())
                    )
                    if has_detail:
                        st.markdown(f"**{candidate}**")
                        if issues is not None and pd.notna(issues) and str(issues).strip():
                            st.markdown(f"- Issues: {issues}")
                        if warnings is not None and pd.notna(warnings) and str(warnings).strip():
                            st.markdown(f"- Warnings: {warnings}")


elif page == "Reports":
    st.subheader("Reports & exports")
    report_pages = [
        ("Final scoring report", scoring_df, "final_scoring_report.csv"),
        ("Project matching report", project_df, "project_match_report.csv"),
        ("Resume analysis report", analysis_df, "analysis_report.csv"),
        ("Candidate ranking report", ranking_df, "candidate_ranking.csv"),
        ("Data quality report", quality_df, "quality_report.csv"),
    ]
    for title, frame, filename in report_pages:
        with st.expander(title, expanded=title == "Final scoring report"):
            if frame.empty:
                show_empty(f"{title} is unavailable or has no rows.")
            else:
                show_table(frame)
                csv_download(frame, filename, f"Download {title} (CSV)")
