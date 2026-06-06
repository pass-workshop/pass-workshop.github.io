# Author: Yuan He
# Date: 2025-09-05
# Description: Extract author IDs from OpenReview groups and count previous submissions

import json
import re

import click
import openreview
import yaml


def resolve_to_profile_ids(
    members: list[str], client: openreview.api.OpenReviewClient
) -> set[str]:
    """Resolve group members to tilde-profile IDs (~Name_Surname1)."""

    # Helper: looks like a profile ID already? (~Name_Surname1)
    TILDE_RE = re.compile(r"^~.+\d+$")
    tilde_ids = {m for m in members if TILDE_RE.match(m)}
    unknowns = [m for m in members if m not in tilde_ids]
    resolved = set(tilde_ids)

    if unknowns:
        profiles = openreview.tools.get_profiles(client, unknowns)
        for p in profiles:
            if p and p.id:
                resolved.add(p.id)
    return resolved


def count_submissions(profile_id: str, client: openreview.api.OpenReviewClient) -> int:
    """
    Count how many submissions (Notes with content['authors']) this profile_id has.
    This searches all venues the account has authored in.
    """
    notes = list(client.get_all_notes(content={"authorids": profile_id}))
    # print(notes)
    return len(notes)


@click.command()
@click.option("--config", "-c", type=click.Path(exists=True), default="config.yaml")
def main(config: str):
    # Load config
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    username = config["openreview_credentials"]["username"]
    password = config["openreview_credentials"]["password"]
    # Instantiate API v2 client (newer API)
    # Docs: https://docs.openreview.net/getting-started/using-the-api/installing-and-instantiating-the-python-client
    client = openreview.api.OpenReviewClient(
        baseurl="https://api2.openreview.net", username=username, password=password
    )

    # Get author groups
    author_groups = config["author_groups"]

    all_profile_ids = set()
    missing_groups = []

    for gid in author_groups:
        try:
            grp = client.get_group(gid)
            members = grp.members or []
            all_profile_ids |= resolve_to_profile_ids(members, client)
        except openreview.OpenReviewException as e:
            missing_groups.append((gid, str(e)))

    # Filter by "at least 3 previous submissions"
    submissions_counter = dict()
    for pid in sorted(all_profile_ids):
        n_subs = count_submissions(pid, client)
        if n_subs >= 0:
            submissions_counter[pid] = n_subs

    with open("author_ids.json", "w") as f:
        json.dump(submissions_counter, f)


main()
