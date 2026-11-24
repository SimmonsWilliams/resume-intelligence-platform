from pathlib import Path
from docx import Document
import json
import csv
from io import BytesIO

BASE_DIR = Path(__file__).resolve().parent

RESUME_DIR = BASE_DIR / "Resume docs"
OUTPUT_DIR = BASE_DIR / "extracted_data"
REPORT_DIR = BASE_DIR / "reports"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def extract_text(file_path):
    """Extract text from DOCX paragraphs and tables."""

    document = Document(file_path)
    content = []

    # Extract paragraphs
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()

        if text:
            content.append(text)

    # Extract tables
    for table in document.tables:
        for row in table.rows:
            row_text = []

            for cell in row.cells:
                text = cell.text.strip()

                if text:
                    row_text.append(text)

            if row_text:
                content.append(" | ".join(row_text))

    return "\n".join(content)


def extract_text_from_stream(stream):
    """Extract DOCX text from an already-created binary stream without disk writes."""
    if hasattr(stream, "seek"):
        stream.seek(0)
    document = Document(stream)
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

    return "\n".join(content)


def process_resumes():

    results = []
    errors = []

    resume_files = list(RESUME_DIR.rglob("*.docx"))

    print(f"Total DOCX files found: {len(resume_files)}")

    for index, file_path in enumerate(resume_files, start=1):

        candidate_id = f"CAND-{index:03d}"

        try:
            full_text = extract_text(file_path)

            if not full_text.strip():
                errors.append({
                    "candidate_id": candidate_id,
                    "file": file_path.name,
                    "error": "Empty or unreadable document"
                })
                continue

            candidate = {
                "candidate_id": candidate_id,
                "source_file": file_path.name,
                "full_text": full_text,
                "character_count": len(full_text),
                "extraction_status": "SUCCESS"
            }

            results.append(candidate)

            # Save individual JSON
            output_file = OUTPUT_DIR / f"{candidate_id}.json"

            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(
                    candidate,
                    f,
                    ensure_ascii=False,
                    indent=4
                )

            print(f"[SUCCESS] {candidate_id}: {file_path.name}")

        except Exception as e:

            errors.append({
                "candidate_id": candidate_id,
                "file": file_path.name,
                "error": str(e)
            })

            print(f"[ERROR] {file_path.name}: {e}")

    # Save combined JSON
    with open(
        OUTPUT_DIR / "all_resumes.json",
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(results, f, ensure_ascii=False, indent=4)

    # Save error report
    with open(
        REPORT_DIR / "extraction_errors.csv",
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=["candidate_id", "file", "error"]
        )

        writer.writeheader()
        writer.writerows(errors)

    print("\n========== EXTRACTION SUMMARY ==========")
    print(f"Total Files: {len(resume_files)}")
    print(f"Successfully Extracted: {len(results)}")
    print(f"Errors: {len(errors)}")
    print("========================================")


if __name__ == "__main__":
    process_resumes()
