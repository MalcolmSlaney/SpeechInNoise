"""
For each (subject, project) pair, print:
  Experimenter: X/T contain false
  Reviewers: [X/T, Y/T, ...] contain false
Uses distinct file counts; total T is the same for experimenter and all reviewers.
"""
import json
from collections import defaultdict

def files_with_any_false(data_str):
    try:
        arr = json.loads(data_str)
        return isinstance(arr, (list, dict)) and (
            any(x is False for x in arr) if isinstance(arr, list)
            else any(v is False for v in arr.values())
        )
    except (TypeError, json.JSONDecodeError):
        return False

# Total files per (subject, project) — denominator for all
total_query = """
SELECT ar.subject, at.project, COUNT(DISTINCT ar.id) AS total
FROM audio_results ar
JOIN audio_trials at ON ar.trial = at.id
GROUP BY ar.subject, at.project
"""
total_by_pair = {(r[0], r[1]): r[2] for r in db.queryall(total_query)}

# Experimenter: count of files with annotations per (subject, project) — patients only
e_count_query = """
SELECT ar.subject, at.project, COUNT(DISTINCT ar.id) AS annotated_count
FROM audio_results ar
JOIN audio_annotations aa ON ar.id = aa.ref
JOIN audio_trials at ON ar.trial = at.id
JOIN user_info ui ON ar.subject = ui.user AND ui.info_key = 'test-type' AND ui.value = 'patient'
WHERE aa.data IS NOT NULL AND aa.data != ''
GROUP BY ar.subject, at.project
"""
e_annotated_count_by_pair = {(r[0], r[1]): r[2] for r in db.queryall(e_count_query)}

# Only include pairs where experimenter has a complete set (annotated count = total)
complete_pairs = {
    (s, p) for (s, p), total in total_by_pair.items()
    if e_annotated_count_by_pair.get((s, p), 0) == total and total > 0
}

# Experimenter: (subject, project) -> distinct file_ids with any false (patients only)
e_query = """
SELECT ar.subject, at.project, ar.id AS file_id, aa.data
FROM audio_results ar
JOIN audio_annotations aa ON ar.id = aa.ref
JOIN audio_trials at ON ar.trial = at.id
JOIN user_info ui ON ar.subject = ui.user AND ui.info_key = 'test-type' AND ui.value = 'patient'
WHERE aa.data IS NOT NULL AND aa.data != ''
"""
e_by_pair = defaultdict(set)
for subject, project, file_id, data_str in db.queryall(e_query):
    if files_with_any_false(data_str):
        e_by_pair[(subject, project)].add(file_id)

# Reviewers: (subject, project) -> list of (reviewer_username, distinct file count with false)
# Only include reviewers who scored all files in that test
r_query = """
SELECT ar.subject, at.project, ar.id AS file_id, ra.data, u.username
FROM audio_results ar
JOIN review_annotations ra ON ar.id = ra.ref
JOIN audio_trials at ON ar.trial = at.id
JOIN users u ON u.id = ra.labeler
JOIN reviewers r ON r.username = u.username AND r.test_type = 'patient'
WHERE ra.data IS NOT NULL
"""
# (subject, project, username) -> set of file_ids with false
r_by_pair_reviewer = defaultdict(set)
# (subject, project, username) -> set of all file_ids they scored (for completeness check)
r_total_files_by_reviewer = defaultdict(set)
for subject, project, file_id, data_str, username in db.queryall(r_query):
    r_total_files_by_reviewer[(subject, project, username)].add(file_id)
    if files_with_any_false(data_str):
        r_by_pair_reviewer[(subject, project, username)].add(file_id)

# Build list of reviewer counts per pair — only reviewers who scored all files
r_lists_by_pair = defaultdict(list)
for (subject, project, username), file_ids_with_false in r_by_pair_reviewer.items():
    total = total_by_pair.get((subject, project), 0)
    files_reviewed = len(r_total_files_by_reviewer[(subject, project, username)])
    if total > 0 and files_reviewed == total:
        r_lists_by_pair[(subject, project)].append((username, len(file_ids_with_false)))
for key in r_lists_by_pair:
    r_lists_by_pair[key].sort(key=lambda x: x[0])

# Print (only pairs with complete experimenter scores)
for (subject, project) in sorted(complete_pairs):
    total = total_by_pair[(subject, project)]
    e_count = len(e_by_pair[(subject, project)])
    r_counts = [c for _, c in r_lists_by_pair[(subject, project)]]
    print(f"Patient {subject}, test {project}:")
    print(f"  Experimenter: {e_count}/{total} contain false")
    reviewer_fracs = "[" + ", ".join(f"{c}/{total}" for c in r_counts) + "]"
    print(f"  Reviewers: {reviewer_fracs} contain false")
    print()
