import json
import random
from flask import session
from review_modules import state, queries


def get_current_file_data(db, user_id, username=None):
    """Get next file to review. Resumes from test_in_progress or picks new test."""
    if not username:
        username = session.get("username")
    
    reviewer_state = state.get_reviewer_state(db, username)
    test_in_progress = reviewer_state['test_in_progress']
    
    if test_in_progress:
        subject_id = test_in_progress["subject"]
        project = test_in_progress["project"]
        current_index = test_in_progress["index"]
        
        cached_total_files = test_in_progress.get("total_files")
        cached_files_reviewed = test_in_progress.get("files_reviewed")
        cached_file_num = test_in_progress.get("current_file_num")
        
        files = queries.get_test_files(db, user_id, subject_id, project)
        
        if not files:
            if queries.is_test_complete(db, user_id, subject_id, project):
                state.add_completed_test(db, username, subject_id, project)
                state.update_most_recent_subject(db, username, subject_id)
            state.clear_test_in_progress(db, username)
        else:
            for idx, file_data in enumerate(files):
                if file_data.get('id') == current_index:
                    total_files = cached_total_files if cached_total_files is not None else queries.get_total_test_files(db, subject_id, project)
                    files_reviewed = queries.get_files_reviewed_in_test(db, user_id, subject_id, project)
                    absolute_file_num = files_reviewed + idx + 1
                    
                    state.update_test_in_progress(db, username, subject_id, project, current_index, total_files, files_reviewed, absolute_file_num)
                    
                    return file_data, subject_id, project, idx, total_files, absolute_file_num
            
            total_files = cached_total_files if cached_total_files is not None else queries.get_total_test_files(db, subject_id, project)
            files_reviewed = queries.get_files_reviewed_in_test(db, user_id, subject_id, project)
            absolute_file_num = files_reviewed + 1
            
            if files:
                state.update_test_in_progress(db, username, subject_id, project, files[0]['id'], total_files, files_reviewed, absolute_file_num)
            return files[0], subject_id, project, 0, total_files, absolute_file_num
    
    remaining_tests = state.get_remaining_tests(db, username, user_id)
    
    if not remaining_tests:
        return None, None, None, None, None, None
    
    most_recent = reviewer_state['most_recent_subject']
    if most_recent:
        filtered_tests = [t for t in remaining_tests if t["subject"] != most_recent]
        if filtered_tests:
            remaining_tests = filtered_tests
    
    if not remaining_tests:
        return None, None, None, None, None, None
    
    min_reviews = min(test["total_reviews"] for test in remaining_tests)
    min_review_tests = [test for test in remaining_tests if test["total_reviews"] == min_reviews]
    
    selected = random.choice(min_review_tests)
    subject_id = selected["subject"]
    project = selected["project"]
    
    files = queries.get_test_files(db, user_id, subject_id, project)
    if not files:
        remaining_tests = [t for t in remaining_tests if (t["subject"], t["project"]) != (subject_id, project)]
        try:
            db.execute(
                "UPDATE reviewers SET remaining_tests = ? WHERE username = ?",
                (json.dumps(remaining_tests), username))
        except:
            pass
        return get_current_file_data(db, user_id, username)
    
    total_files = queries.get_total_test_files(db, subject_id, project)
    files_reviewed = queries.get_files_reviewed_in_test(db, user_id, subject_id, project)
    first_file_id = files[0]['id']
    current_file_num = files_reviewed + 1
    
    state.update_test_in_progress(db, username, subject_id, project, first_file_id, total_files, files_reviewed, current_file_num)
    
    remaining_tests = [t for t in remaining_tests if (t["subject"], t["project"]) != (subject_id, project)]
    try:
        db.execute(
            "UPDATE reviewers SET remaining_tests = ? WHERE username = ?",
            (json.dumps(remaining_tests), username))
    except:
        pass
    
    return files[0], subject_id, project, 0, total_files, current_file_num
