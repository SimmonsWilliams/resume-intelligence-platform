import csv
import json
import re
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent

INPUT_FILE = BASE_DIR / "extracted_data" / "all_resumes.json"
OUTPUT_DIR = BASE_DIR / "analyzed_data_v2"
REPORT_DIR = BASE_DIR / "reports"
ONTOLOGY_FILE = BASE_DIR / "skill_ontology.json"

OUTPUT_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)

SECTION_ALIASES = {
    "education": [
        "education", "academic background", "educational qualification"
    ],
    "experience": [
        "experience", "work experience", "professional experience",
        "employment history", "work history"
    ],
    "projects": [
        "projects", "projects deliverables", "academic projects",
        "personal projects"
    ],
    "certifications": [
        "certifications", "certifications licenses",
        "licenses certifications", "certificates"
    ],
    "skills": [
        "skills", "core skills", "technical skills",
        "key skills", "areas of expertise", "competencies"
    ],
    "summary": [
        "professional summary", "summary", "profile",
        "career objective", "professional profile"
    ],
    "awards": [
        "awards honors", "honors awards", "achievements"
    ]
}

# Starter ontology. Extend it through skill_ontology.json.
DEFAULT_ONTOLOGY = {
    "technology": [
        "Python", "Java", "JavaScript", "React", "Spring Boot",
        "SQL", "MySQL", "PostgreSQL", "Selenium", "BeautifulSoup",
        "Web Scraping", "FastAPI", "Django", "Flask", "REST API",
        "HTML", "CSS", "Git", "Docker", "Kubernetes", "Linux",
        "AWS", "Azure", "Jenkins", "Bash", "Pandas", "NumPy"
    ],
    "design": [
        "Figma", "Adobe XD", "Wireframing", "Prototyping",
        "User Research", "Usability Testing", "UI Design",
        "UX Design", "Responsive Design"
    ],
    "environment": [
        "OpenLCA", "GaBi", "SimaPro", "Life Cycle Assessment",
        "LCA", "ISO 14040", "ISO 14044",
        "Environmental Impact Assessment", "Aspen Plus",
        "Carbon Accounting", "GHG Management",
        "ESG Reporting", "Sustainability", "CEMS",
        "CAAQMS", "STP", "ETP", "CPCB"
    ],
    "business": [
        "Excel", "Power BI", "Accounting", "Financial Reporting",
        "Digital Marketing", "Sales", "Project Management",
        "Human Resources", "Recruitment"
    ]
}


def normalize_text(value):
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def load_ontology():
    if not ONTOLOGY_FILE.exists():
        with ONTOLOGY_FILE.open("w", encoding="utf-8") as file:
            json.dump(DEFAULT_ONTOLOGY, file, indent=4, ensure_ascii=False)
        print("[INFO] Created starter skill_ontology.json")

    with ONTOLOGY_FILE.open(encoding="utf-8") as file:
        ontology = json.load(file)

    if not isinstance(ontology, dict):
        raise ValueError("Ontology must be a JSON object of categories and skills.")

    skills = {}
    for category, entries in ontology.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, str) and entry.strip():
                skills[entry.strip()] = category

    return skills


def get_sections(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    heading_lookup = {
        normalize_text(alias): section
        for section, aliases in SECTION_ALIASES.items()
        for alias in aliases
    }

    detected = {}
    current_section = "other"

    for line in lines:
        key = normalize_text(line)

        if key in heading_lookup:
            current_section = heading_lookup[key]
            detected.setdefault(current_section, [])
        else:
            detected.setdefault(current_section, []).append(line)

    return detected



def compile_skill_patterns(ontology):
    patterns = []

    # Match longer skill names before shorter skill names.
    # Example: Carbon Accounting before Accounting.
    sorted_skills = sorted(
        ontology.items(),
        key=lambda item: len(item[0]),
        reverse=True
    )

    for skill, category in sorted_skills:
        pattern = re.compile(
            r"(?<![a-zA-Z0-9])"
            + re.escape(skill)
            + r"(?![a-zA-Z0-9])",
            re.IGNORECASE
        )

        patterns.append((skill, category, pattern))

    return patterns




def extract_skill_evidence(sections, patterns):
    evidence_map = {}

    for section, lines in sections.items():
        for line in lines:
            matches = []

            # Find every skill occurrence in this line
            for skill, category, pattern in patterns:
                for match in pattern.finditer(line):
                    matches.append({
                        "start": match.start(),
                        "end": match.end(),
                        "skill": skill,
                        "category": category
                    })

            # Prefer longer phrases when matches overlap
            matches.sort(
                key=lambda item: (
                    item["end"] - item["start"]
                ),
                reverse=True
            )

            accepted_matches = []

            for candidate in matches:
                overlaps = any(
                    candidate["start"] < accepted["end"]
                    and candidate["end"] > accepted["start"]
                    for accepted in accepted_matches
                )

                if not overlaps:
                    accepted_matches.append(candidate)

            # Save only non-overlapping skill matches
            for item in accepted_matches:
                skill = item["skill"]
                category = item["category"]
                key = normalize_text(skill)

                if key not in evidence_map:
                    evidence_map[key] = {
                        "skill": skill,
                        "category": category,
                        "evidence": [],
                        "sections": set()
                    }

                evidence_map[key]["evidence"].append(line)
                evidence_map[key]["sections"].add(section)

    results = []

    for item in evidence_map.values():
        sections_found = sorted(item["sections"])
        evidence_lines = list(dict.fromkeys(item["evidence"]))

        if any(s in sections_found for s in
               ["experience", "projects"]):
            evidence_type = "evidence_backed"
            confidence = "higher"
        elif "skills" in sections_found:
            evidence_type = "explicit_mention"
            confidence = "moderate"
        else:
            evidence_type = "explicit_mention"
            confidence = "needs_review"

        results.append({
            "skill": item["skill"],
            "category": item["category"],
            "sections": sections_found,
            "evidence": evidence_lines,
            "evidence_count": len(evidence_lines),
            "evidence_type": evidence_type,
            "confidence": confidence,
            "verification_required": True
        })

    return sorted(results, key=lambda x: x["skill"].lower())



def discover_unknown_candidates(sections, known_patterns):
    """
    Finds possible skill phrases from skill-labelled sections.
    These are suggestions only, not verified skills.
    """
    candidates = defaultdict(set)

    for line in sections.get("skills", []):
        for phrase in re.split(r"[,;|•]", line):
            phrase = phrase.strip(" :-\t")
            phrase = re.sub(r"\s+", " ", phrase)

            if not 2 <= len(phrase) <= 70:
                continue

            if not re.search(r"[a-zA-Z]", phrase):
                continue

            if any(pattern.search(phrase)
                   for _, _, pattern in known_patterns):
                continue

            if len(phrase.split()) > 8:
                continue

            candidates[normalize_text(phrase)].add(phrase)

    return [
        {
            "candidate_term": sorted(values)[0],
            "source": "skills_section",
            "status": "pending_review"
        }
        for values in candidates.values()
    ]


def analyze_candidate(candidate, patterns):
    text = candidate.get("full_text", "")
    sections = get_sections(text)

    skill_evidence = extract_skill_evidence(sections, patterns)
    unknown_candidates = discover_unknown_candidates(
        sections, patterns
    )

    profile = {
        "candidate_id": candidate.get("candidate_id", "UNKNOWN"),
        "source_file": candidate.get("source_file", ""),
        "skills": [item["skill"] for item in skill_evidence],
        "skill_evidence": skill_evidence,
        "potential_skill_candidates": unknown_candidates,
        "education": sections.get("education", []),
        "experience": sections.get("experience", []),
        "experience_evidence": [
            line for line in sections.get("experience", [])
            if re.search(r"\b(?:19|20)\d{2}\b", line)
        ],
        "projects": sections.get("projects", []),
        "certifications": sections.get("certifications", []),
        "professional_summary": sections.get("summary", []),
        "awards": sections.get("awards", []),
        "section_counts": {
            section: len(lines)
            for section, lines in sections.items()
        },
        "extraction_status": "ANALYZED",
        "verification_required": True,
        "analyzer_version": "2.0"
    }

    return profile


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT_FILE}")

    with INPUT_FILE.open(encoding="utf-8") as file:
        candidates = json.load(file)

    if not isinstance(candidates, list):
        raise ValueError("all_resumes.json must contain a JSON list.")

    ontology = load_ontology()
    patterns = compile_skill_patterns(ontology)

    profiles = []
    errors = []

    for candidate in candidates:
        candidate_id = candidate.get("candidate_id", "UNKNOWN")

        try:
            profile = analyze_candidate(candidate, patterns)
            profiles.append(profile)

            output_file = OUTPUT_DIR / f"{candidate_id}.json"
            with output_file.open("w", encoding="utf-8") as file:
                json.dump(profile, file, indent=4, ensure_ascii=False)

            print(
                f"[ANALYZED] {candidate_id} | "
                f"Skills: {len(profile['skills'])} | "
                f"Unknown suggestions: "
                f"{len(profile['potential_skill_candidates'])}"
            )

        except Exception as error:
            errors.append({
                "candidate_id": candidate_id,
                "error": str(error)
            })
            print(f"[ERROR] {candidate_id}: {error}")

    with (OUTPUT_DIR / "all_profiles.json").open(
        "w", encoding="utf-8"
    ) as file:
        json.dump(profiles, file, indent=4, ensure_ascii=False)

    with (OUTPUT_DIR / "unknown_skill_candidates.json").open(
        "w", encoding="utf-8"
    ) as file:
        unknown = [
            {
                "candidate_id": profile["candidate_id"],
                **candidate
            }
            for profile in profiles
            for candidate in profile["potential_skill_candidates"]
        ]
        json.dump(unknown, file, indent=4, ensure_ascii=False)

    with (REPORT_DIR / "analysis_report_v2.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.writer(file)
        writer.writerow([
            "Candidate ID", "Skills Count", "Evidence-backed Skills",
            "Unknown Suggestions", "Education Entries",
            "Experience Entries", "Projects Count",
            "Certifications Count"
        ])

        for profile in profiles:
            writer.writerow([
                profile["candidate_id"],
                len(profile["skills"]),
                sum(
                    x["evidence_type"] == "evidence_backed"
                    for x in profile["skill_evidence"]
                ),
                len(profile["potential_skill_candidates"]),
                len(profile["education"]),
                len(profile["experience"]),
                len(profile["projects"]),
                len(profile["certifications"])
            ])

    with (REPORT_DIR / "analysis_errors_v2.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.writer(file)
        writer.writerow(["Candidate ID", "Error"])
        for error in errors:
            writer.writerow([error["candidate_id"], error["error"]])

    print("\n========== V2 ANALYSIS SUMMARY ==========")
    print(f"Input candidates: {len(candidates)}")
    print(f"Successfully analyzed: {len(profiles)}")
    print(f"Errors: {len(errors)}")
    print(f"Ontology skills: {len(ontology)}")
    print(f"Output: {OUTPUT_DIR}")
    print("Report: reports/analysis_report_v2.csv")
    print("========================================")


if __name__ == "__main__":
    main()
