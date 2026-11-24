
import json
from pathlib import Path


# Project directory
BASE_DIR = Path(__file__).resolve().parent

# Job descriptions directory
JOB_DIR = BASE_DIR / "job_descriptions"


def load_job_description(file_path):

    with open(file_path, "r", encoding="utf-8") as file:
        job_data = json.load(file)

    return job_data


def analyze_job(job_data):

    print("\n========== JOB ANALYSIS ==========")

    print("Job ID:", job_data.get("job_id"))

    print("Job Title:", job_data.get("job_title"))

    print("\nRequired Skills:")

    for skill in job_data.get("required_skills", []):
        print("-", skill)

    print("\nPreferred Skills:")

    for skill in job_data.get("preferred_skills", []):
        print("-", skill)

    print("\nEducation:")

    for education in job_data.get("education", []):
        print("-", education)

    print("\nExperience:")

    print(job_data.get("experience", {}))

    print("==================================")


def main():

    job_files = list(JOB_DIR.glob("*.json"))

    print("Total Job Descriptions:", len(job_files))

    for file_path in job_files:

        job_data = load_job_description(file_path)

        analyze_job(job_data)


if __name__ == "__main__":
    main()
