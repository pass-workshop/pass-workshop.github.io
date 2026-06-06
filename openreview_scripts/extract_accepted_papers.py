#!/usr/bin/env python3
"""
Extract accepted papers directly from NeurIPS.cc/2025/Workshop/SEA venue.

This script fetches papers marked with venueid=NeurIPS.cc/2025/Workshop/SEA,
which are the officially accepted papers. The venue field indicates whether
each paper is an Oral or Poster presentation.

Outputs:
  accepted_papers.csv (columns: paper_number, title, authors, presentation_type)

Requirements:
  pip install openreview-py pandas
"""

import sys
import click
import yaml
import pandas as pd

try:
    import openreview
except ImportError:
    print("Please install dependencies first: pip install openreview-py pandas")
    sys.exit(1)

VENUE_ID = "NeurIPS.cc/2025/Workshop/SEA"


def get_paper_number(note):
    if hasattr(note, "number") and note.number is not None:
        return int(note.number)
    content = note.content or {}
    for k in ["number", "paper_number", "submission_number"]:
        v = content.get(k)
        if isinstance(v, dict):
            v = v.get("value")
        if v is not None:
            try:
                return int(v)
            except Exception:
                pass
    return -1


def get_title(note):
    content = note.content or {}
    title = content.get("title", "")
    if isinstance(title, dict):
        title = title.get("value", "")
    return str(title).strip()


def get_authors(note):
    content = note.content or {}
    authors = content.get("authors", [])
    if isinstance(authors, dict):
        authors = authors.get("value", [])
    if isinstance(authors, list):
        return ", ".join([str(a) for a in authors])
    return str(authors).strip()


def get_venue_field(note):
    """Extract venue field which indicates presentation type"""
    content = note.content or {}
    venue = content.get("venue", "")
    if isinstance(venue, dict):
        venue = venue.get("value", "")
    return str(venue).strip()


@click.command()
@click.option("--config", "-c", type=click.Path(exists=True), default="config.yaml")
@click.option("--output", "-o", type=str, default="accepted_papers.csv")
def main(config: str, output: str):
    with open(config, "r") as f:
        config_data = yaml.safe_load(f)

    client = openreview.api.OpenReviewClient(
        baseurl="https://api2.openreview.net",
        username=config_data["openreview_credentials"]["username"],
        password=config_data["openreview_credentials"]["password"],
    )

    print("Fetching all venue notes...")

    # Get all notes with this venueid (should be 93 accepted papers)
    venue_notes = list(
        openreview.tools.iterget_notes(client, content={"venueid": VENUE_ID})
    )
    print(f"Found {len(venue_notes)} accepted papers with venueid={VENUE_ID}")

    # Extract accepted papers
    accepted_papers = []

    for note in venue_notes:
        venue_field = get_venue_field(note)

        # All notes with this venueid are accepted papers
        # The venue field tells us if it's Oral or Poster
        paper_no = get_paper_number(note)
        title = get_title(note)
        authors = get_authors(note)

        # Determine presentation type from venue field
        # e.g., "SEA @ NeurIPS 2025 Poster" or "SEA @ NeurIPS 2025 Oral"
        venue_lower = venue_field.lower()
        if "oral" in venue_lower:
            pres_type = "Oral"
        elif "poster" in venue_lower:
            pres_type = "Poster"
        else:
            pres_type = ""

        accepted_papers.append(
            {
                "paper_number": paper_no,
                "title": title,
                "authors": authors,
                "presentation_type": pres_type,
            }
        )

    if accepted_papers:
        df = pd.DataFrame(accepted_papers).sort_values("paper_number")
        df.to_csv(output, index=False)
        print(f"\nWrote {output} with {len(accepted_papers)} accepted papers.")

        oral_count = sum(1 for p in accepted_papers if p["presentation_type"] == "Oral")
        poster_count = sum(
            1 for p in accepted_papers if p["presentation_type"] == "Poster"
        )
        print(f"  - Oral: {oral_count}")
        print(f"  - Poster: {poster_count}")
    else:
        print("No accepted papers found.")


if __name__ == "__main__":
    main()
