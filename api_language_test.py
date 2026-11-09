import csv

import pytest

from api import PROJECT_LANGUAGES, default_language
from storage import relpath


def languages_in(transcript):
    with open(relpath("metadata", transcript), encoding="utf-8") as f:
        return {row[1].strip() for row in csv.reader(f) if row}


@pytest.mark.parametrize("project", sorted(PROJECT_LANGUAGES))
def test_default_language_matches_the_transcript(project):
    assert default_language(project) in languages_in(
        f"{project}_transcript.csv")


def test_other_projects_default_to_english():
    assert default_language("quick") == "en"
    assert default_language("azbio") == "en"
