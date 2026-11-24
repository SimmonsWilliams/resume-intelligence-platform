
import json
import re
import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

INPUT_FILE = BASE_DIR / "extracted_data" / "all_resumes.json"
OUTPUT_DIR = BASE_DIR / "analyzed_data"
REPORT_DIR = BASE_DIR / "reports"

OUTPUT_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)

# Skills relevant to the supplied job profiles
SKILLS = [
    "Python", "Java", "JavaScript", "React",
    "Spring Boot", "SQL", "MySQL", "PostgreSQL",
    "Selenium", "Web Scraping", "BeautifulSoup",
    "FastAPI", "Django", "Flask", "REST API",
    "HTML", "CSS", "Git", "Docker", "Kubernetes",
    "Figma", "Adobe XD", "Wireframing",
    "Prototyping", "User Research", "Usability Testing",
    "UI Design", "UX Design", "Responsive Design",
    "OpenLCA", "GaBi", "SimaPro",
    "Life Cycle Assessment", "LCA",
    "ISO 14040", "ISO 14044",
    "Environmental Impact Assessment",
    "Aspen Plus", "Power BI", "AutoCAD",
    "Carbon Accounting", "GHG Management",
    "ESG Reporting", "Sustainability",
    "Excel", "Pandas", "NumPy"
]

SECTION_ALIASES = {
    "education": ["education", "academic background"],
    "experience": ["experience", "work experience",
                   "professional experience", "employment history"],
    "projects": ["projects", "projects deliverables",
                 "academic projects", "personal projects"],
    "certifications": ["certifications", "certifications licenses",
                       "licenses certifications"],
    "skills": ["skills", "core skills", "technical skills",
               "key skills"],
    "summary": ["professional summary", "summary",
                "profile", "career objective"],
    "awards": ["awards honors", "honors awards"]
}


def normalize_heading(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def get_sections(text):

    lines = [line.strip() for line in text.splitlines()
             if line.strip()]

    heading_lookup = {}

    for section, aliases in SECTION_ALIASES.items():
        for alias in aliases:
            heading_lookup[normalize_heading(alias)] = section

    detected = {}

    for index, line in enumerate(lines):
        normalized = normalize_heading(line)

        if normalized in heading_lookup:
            section_name = heading_lookup[normalized]

            end = index + 1

            while end < len(lines):
                next_heading = normalize_heading(lines[end])

                if next_heading in heading_lookup:
                    break

                end += 1

            detected[section_name] = lines[index + 1:end]

    return detected


def find_skills(text):

    found = []

    for skill in SKILLS:
        pattern = (
            r"(?<![a-zA-Z0-9])"
            + re.escape(skill)
            + r"(?![a-zA-Z0-9])"
        )

        if re.search(pattern, text, re.IGNORECASE):
            found.append(skill)

    return sorted(set(found), key=str.lower)


def find_experience_evidence(lines):

    results = []

    date_pattern = re.compile(
        r"\b(?:19|20)\d{2}\b",
        re.IGNORECASE
    )

    for line in lines:
        if date_pattern.search(line):
            results.append(line)

    return results


def analyze_candidate(candidate):

    text = candidate.get("full_text", "")

    sections = get_sections(text)

    skills = find_skills(text)

    education = sections.get("education", [])
    experience = sections.get("experience", [])
    projects = sections.get("projects", [])
    certifications = sections.get("certifications", [])
    summary = sections.get("summary", [])
    awards = sections.get("awards", [])

    profile = {
        "candidate_id": candidate["candidate_id"],
        "source_file": candidate["source_file"],

        "skills": skills,

        "education": education,

        "experience": experience,

        "experience_evidence": find_experience_evidence(
            experience
        ),

        "projects": projects,

        "certifications": certifications,

        "professional_summary": summary,

        "awards": awards,

        "extraction_status": "ANALYZED",

        "verification_required": True
    }

    return profile


def main():

    if not INPUT_FILE.exists():
        print("ERROR: Input JSON file not found!")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as file:
        candidates = json.load(file)

    profiles = []

    for candidate in candidates:

        try:
            profile = analyze_candidate(candidate)

            profiles.append(profile)

            output_file = (
                OUTPUT_DIR /
                f"{candidate['candidate_id']}.json"
            )

            with open(output_file, "w", encoding="utf-8") as file:
                json.dump(
                    profile,
                    file,
                    ensure_ascii=False,
                    indent=4
                )

            print(
                f"[ANALYZED] {candidate['candidate_id']} "
                f"| Skills: {len(profile['skills'])}"
            )

        except Exception as error:

            print(
                f"[ERROR] {candidate.get('candidate_id')}: "
                f"{error}"
            )

    # Save all analyzed profiles
    with open(
        OUTPUT_DIR / "all_profiles.json",
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            profiles,
            file,
            ensure_ascii=False,
            indent=4
        )

    # Create summary report
    with open(
        REPORT_DIR / "analysis_report.csv",
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        writer = csv.writer(file)

        writer.writerow([
            "Candidate ID",
            "Skills Count",
            "Education Entries",
            "Experience Entries",
            "Projects Count",
            "Certifications Count"
        ])

        for profile in profiles:
            writer.writerow([
                profile["candidate_id"],
                len(profile["skills"]),
                len(profile["education"]),
                len(profile["experience"]),
                len(profile["projects"]),
                len(profile["certifications"])
            ])

    print("\n========== ANALYSIS SUMMARY ==========")
    print(f"Total Candidates: {len(candidates)}")
    print(f"Successfully Analyzed: {len(profiles)}")
    print("Output: analyzed_data/all_profiles.json")
    print("Report: reports/analysis_report.csv")
    print("======================================")


if __name__ == "__main__":
    main()
