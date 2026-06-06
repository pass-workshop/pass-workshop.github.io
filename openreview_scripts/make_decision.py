#!/usr/bin/env python3
"""
Extract decisions & flag low-score accepts (based on AC meta-review) for NeurIPS.cc/2025/Workshop/SEA.

Outputs:
  1) sea_decisions.csv               (columns: paper_number, decision, comment)
  2) sea_flagged_low_score_accept.csv (column: paper_number)

Requirements:
  pip install openreview-py pandas
"""

import re
import sys
import click
import yaml
from typing import List, Optional
import pandas as pd

try:
    import openreview
except ImportError:
    print("Please install dependencies first: pip install openreview-py pandas")
    sys.exit(1)

VENUE_ID = "NeurIPS.cc/2025/Workshop/SEA"

# --- Helpers ---------------------------------------------------------------


def find_submission_invitation(client) -> str:
    """
    Try common submission invitations in priority order and return the first that exists.
    """
    candidates = [
        f"{VENUE_ID}/-/-/Blind_Submission",
        f"{VENUE_ID}/-/-/Blind_Submission2",
        f"{VENUE_ID}/-/-/Submission",
        f"{VENUE_ID}/-/-/Paper",
        f"{VENUE_ID}/-/Submission",
        f"{VENUE_ID}/-/Blind_Submission",
    ]
    for inv in candidates:
        try:
            client.get_invitation(inv)
            return inv
        except openreview.OpenReviewException:
            continue
    raise RuntimeError("Could not find a submission invitation for this venue.")


def iter_notes(client, **kwargs):
    """Generator over notes using tools.iterget_notes with robust pagination."""
    return openreview.tools.iterget_notes(client=client, **kwargs)


def parse_numeric_score(value: str) -> Optional[float]:
    """
    Extract a numeric score from common OpenReview rating strings, e.g.:
      '6: Weak Accept', '3 - Borderline', '7', '4.5: Something', etc.
    Returns float or None if not parseable.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    # Look for a leading number (possibly float)
    m = re.match(r"\s*([0-9]+(\.[0-9]+)?)", str(value))
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def get_reviews_for_forum(client, forum_id: str) -> List[openreview.api.Note]:
    """
    Fetch notes in the thread and keep those that look like reviews.
    """
    # Pull all replies for the forum and filter by invitation name
    replies = list(iter_notes(client, forum=forum_id))
    reviews = []
    for n in replies:
        inv = (n.invitations[0] if n.invitations else "").lower()
        if "review" in inv and ("official" in inv or "review" in inv):
            reviews.append(n)
    return reviews


def average_review_score(review_notes: List[openreview.api.Note]) -> Optional[float]:
    """
    Compute an average score from review notes, trying common score fields.
    """
    score_fields = [
        "rating",
        "overall_assessment",
        "overall recommendation",
        "overall_recommendation",
        "recommendation",
        "overall",
        "overall_score",
    ]
    scores: List[float] = []
    for r in review_notes:
        content = r.content or {}
        # Try a few likely field names; some venues nest fields differently
        for key in score_fields:
            # try exact, then case-insensitive fallback
            candidates = []
            if key in content:
                candidates.append(content[key])
            else:
                # pick first value whose key matches case-insensitively
                for k, v in content.items():
                    if k.replace(" ", "").lower() == key.replace(" ", "").lower():
                        candidates.append(v)
                        break
            for val in candidates:
                sc = parse_numeric_score(
                    val if not isinstance(val, dict) else val.get("value")
                )
                if sc is not None:
                    scores.append(sc)
                    break
            if scores and scores[-1] is not None:
                break
    if not scores:
        return None
    return sum(scores) / len(scores)


def get_decision_for_forum(client, forum_id: str) -> Optional[str]:
    """
    Fetch meta-review recommendation only (skip official decisions).
    """
    # Look for meta-review with a 'recommendation' field
    meta_candidates = [
        n
        for n in iter_notes(client, forum=forum_id)
        if n.invitations
        and ("Meta_Review" in n.invitations[0] or "Meta-Review" in n.invitations[0])
    ]
    if meta_candidates:
        # Use the latest meta-review by creation time
        meta = sorted(meta_candidates, key=lambda x: x.cdate or 0, reverse=True)[0]
        content = meta.content or {}
        for key in [
            "recommendation",
            "final_recommendation",
            "final decision",
            "decision",
        ]:
            if key in content:
                val = content[key]
                if isinstance(val, dict):
                    val = val.get("value", "")
                return str(val).strip() if val else None

    return None


def get_paper_number(note: openreview.api.Note) -> Optional[int]:
    """
    Robustly extract the paper number.
    """
    # v2 Notes often have .number; Blind submissions often do too.
    if hasattr(note, "number") and note.number is not None:
        return int(note.number)
    # Sometimes buried in content
    for k in ["number", "paper_number", "submission_number"]:
        v = (note.content or {}).get(k)
        if isinstance(v, dict):
            v = v.get("value")
        if v is not None:
            try:
                return int(v)
            except Exception:
                pass
    return None


# --- Main ------------------------------------------------------------------


@click.command()
@click.option("--config", "-c", type=click.Path(exists=True), default="config.yaml")
def main(config: str):
    # Load config
    with open(config, "r") as f:
        config = yaml.safe_load(f)

    username = config["openreview_credentials"]["username"]
    password = config["openreview_credentials"]["password"]
    # Instantiate API v2 client (newer API)
    # Docs: https://docs.openreview.net/getting-started/using-the-api/installing-and-instantiating-the-python-client
    client = openreview.api.OpenReviewClient(
        baseurl="https://api2.openreview.net", username=username, password=password
    )

    try:
        sub_inv = find_submission_invitation(client)
    except RuntimeError as e:
        print(str(e))
        sys.exit(2)

    submissions = list(iter_notes(client, invitation=sub_inv))
    if not submissions:
        print("No submissions found.")
        sys.exit(0)

    rows = []
    flagged_low_score_accept = []

    for sub in submissions:
        forum = sub.forum or sub.id
        paper_no = get_paper_number(sub)
        if paper_no is None:
            # Fallback: try to parse from the 'number' in the URL-style ID if present
            paper_no = (
                sub.number if hasattr(sub, "number") and sub.number is not None else -1
            )

        decision = get_decision_for_forum(client, forum_id=forum)
        # Normalize decision text a bit
        decision_str = (decision or "").strip()

        # Average review score
        reviews = get_reviews_for_forum(client, forum_id=forum)
        avg_score = average_review_score(reviews)

        # Flag: accepted + avg < 4.0
        # Heuristic: treat any decision that starts with "Accept" (case-insensitive) as accepted.
        accepted = decision_str.lower().startswith("accept")
        if accepted and (avg_score is not None) and (avg_score < 4.0):
            flagged_low_score_accept.append(paper_no)

        # Append CSV row with empty comment
        rows.append({"paper_number": paper_no, "decision": decision_str, "comment": ""})

    # Write CSVs
    df = pd.DataFrame(rows).sort_values("paper_number")
    df.to_csv("sea_decisions.csv", index=False)

    flagged = pd.DataFrame(
        sorted(set([p for p in flagged_low_score_accept if p is not None])),
        columns=["paper_number"],
    )
    flagged.to_csv("sea_flagged_low_score_accept.csv", index=False)

    print("Wrote sea_decisions.csv (paper_number, decision, comment).")
    if len(flagged):
        print(
            "Wrote sea_flagged_low_score_accept.csv with the accepted papers whose avg score < 4.0."
        )
    else:
        print(
            "No accepted papers with average score < 4.0 were found (or no scores available)."
        )


if __name__ == "__main__":
    main()
