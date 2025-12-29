import json
from flask import session


def get_reviewer_state(db, username):
    """Get reviewer state from database. Recalculates total_reviews for accuracy."""
    try:
        result = db.queryone(
            "SELECT test_in_progress, completed_tests, remaining_tests, most_recent_subject, total_reviews, played_audio FROM reviewers WHERE username = ?",
            (username,))
        if result:
            user_result = db.queryone("SELECT id FROM users WHERE username = ?", (username,))
            if user_result:
                user_id = user_result[0]
                count_result = db.queryone("SELECT COUNT(*) FROM review_annotations WHERE labeler = ?", (user_id,))
                actual_count = count_result[0] if count_result else 0
                stored_count = result[4] if result[4] is not None else 0
                
                if actual_count != stored_count:
                    try:
                        db.execute("UPDATE reviewers SET total_reviews = ? WHERE username = ?", (actual_count, username))
                        print(f"DEBUG: Corrected total_reviews for '{username}' from {stored_count} to {actual_count}")
                    except:
                        pass
                # dictionary holding reviewer state
                return {
                    'test_in_progress': json.loads(result[0]) if result[0] else None,
                    'completed_tests': json.loads(result[1]) if result[1] else [],
                    'remaining_tests': json.loads(result[2]) if result[2] else [],
                    'most_recent_subject': result[3],
                    'total_reviews': actual_count,
                    'played_audio': json.loads(result[5]) if result[5] else []
                }
            else:
                stored_count = result[4] if result[4] is not None else 0
                return {
                    'test_in_progress': json.loads(result[0]) if result[0] else None,
                    'completed_tests': json.loads(result[1]) if result[1] else [],
                    'remaining_tests': json.loads(result[2]) if result[2] else [],
                    'most_recent_subject': result[3],
                    'total_reviews': stored_count,
                    'played_audio': json.loads(result[5]) if result[5] else []
                }
    except Exception as e:
        print(f"WARNING: Failed to get reviewer state for '{username}': {e}")
    return {
        'test_in_progress': None,
        'completed_tests': [],
        'remaining_tests': [],
        'most_recent_subject': None,
        'total_reviews': 0,
        'played_audio': []
    }


def update_test_in_progress(db, username, subject_id, project, current_index, total_files=None, files_reviewed=None, current_file_num=None):
    """Update test_in_progress with current progress."""
    if not username:
        return
    try:
        progress_data = {
            "subject": subject_id,
            "project": project,
            "index": current_index
        }
        if total_files is not None:
            progress_data["total_files"] = total_files
        if files_reviewed is not None:
            progress_data["files_reviewed"] = files_reviewed
        if current_file_num is not None:
            progress_data["current_file_num"] = current_file_num
        
        test_in_progress = json.dumps(progress_data)
        db.execute(
            "UPDATE reviewers SET test_in_progress = ? WHERE username = ?",
            (test_in_progress, username))
    except Exception as e:
        print(f"WARNING: Failed to update test_in_progress for reviewer '{username}': {e}")


def clear_test_in_progress(db, username):
    """Clear test_in_progress."""
    if not username:
        return
    try:
        db.execute(
            "UPDATE reviewers SET test_in_progress = NULL WHERE username = ?",
            (username,))
    except Exception as e:
        print(f"WARNING: Failed to clear test_in_progress for reviewer '{username}': {e}")


def add_played_audio(db, username, file_id):
    """Add file_id to played_audio list to monitor participants leaving without reviewing."""
    if not username or not file_id:
        return
    try:
        state = get_reviewer_state(db, username)
        played_audio = state['played_audio']
        if file_id not in played_audio:
            played_audio.append(file_id)
            db.execute(
                "UPDATE reviewers SET played_audio = ? WHERE username = ?",
                (json.dumps(played_audio), username))
    except Exception as e:
        print(f"WARNING: Failed to add played_audio for reviewer '{username}': {e}")

# when removed, take it out again
def remove_played_audio(db, username, file_id):
    """Remove file_id from played_audio list."""
    if not username or not file_id:
        return
    try:
        state = get_reviewer_state(db, username)
        played_audio = state['played_audio']
        if file_id in played_audio:
            played_audio.remove(file_id)
            db.execute(
                "UPDATE reviewers SET played_audio = ? WHERE username = ?",
                (json.dumps(played_audio), username))
    except Exception as e:
        print(f"WARNING: Failed to remove played_audio for reviewer '{username}': {e}")


def increment_total_reviews(db, username):
    """Update total_reviews count (recalculated from actual count)."""
    if not username:
        return
    try:
        user_result = db.queryone("SELECT id FROM users WHERE username = ?", (username,))
        if not user_result:
            print(f"WARNING: User '{username}' not found in users table, cannot increment total_reviews")
            return
        
        user_id = user_result[0]
        count_result = db.queryone("SELECT COUNT(*) FROM review_annotations WHERE labeler = ?", (user_id,))
        actual_count = count_result[0] if count_result else 0
        
        db.execute(
            "UPDATE reviewers SET total_reviews = ? WHERE username = ?",
            (actual_count, username))
        print(f"DEBUG: Updated total_reviews for '{username}' to {actual_count}")
    except Exception as e:
        print(f"WARNING: Failed to increment total_reviews for reviewer '{username}': {e}")
        import traceback
        traceback.print_exc()


def add_completed_test(db, username, subject_id, project):
    """Add test to completed_tests list."""
    if not username:
        return
    try:
        state = get_reviewer_state(db, username)
        completed_tests = state['completed_tests']
        
        test_pair = {"subject": subject_id, "project": project}
        if test_pair not in completed_tests:
            completed_tests.append(test_pair)
            db.execute(
                "UPDATE reviewers SET completed_tests = ? WHERE username = ?",
                (json.dumps(completed_tests), username))
    except Exception as e:
        print(f"WARNING: Failed to add completed test for reviewer '{username}': {e}")


def update_most_recent_subject(db, username, subject_id):
    """Update most_recent_subject."""
    if not username or not subject_id:
        return
    
    try:
        reviewer_exists = db.queryone("SELECT 1 FROM reviewers WHERE username = ?", (username,))
        if reviewer_exists:
            db.execute(
                "UPDATE reviewers SET most_recent_subject = ? WHERE username = ?",
                (subject_id, username))
    except Exception as e:
        print(f"WARNING: Failed to update most_recent_subject for reviewer '{username}': {e}")


def calculate_and_update_remaining_tests(db, username, user_id):
    """Calculate and update remaining_tests (excludes completed and in-progress)."""
    if not username:
        return []
    
    try:
        from review_modules import queries
        available_tests = queries.get_available_tests(db, user_id)
        state = get_reviewer_state(db, username)
        completed_tests = state['completed_tests']
        completed_set = {(t["subject"], t["project"]) for t in completed_tests}
        
        test_in_progress = state['test_in_progress']
        in_progress_set = set()
        if test_in_progress:
            in_progress_set.add((test_in_progress["subject"], test_in_progress["project"]))
        
        remaining = [
            {"subject": test[0], "project": test[1], "total_reviews": test[2]}
            for test in available_tests
            if (test[0], test[1]) not in completed_set and (test[0], test[1]) not in in_progress_set
        ]
        
        db.execute(
            "UPDATE reviewers SET remaining_tests = ? WHERE username = ?",
            (json.dumps(remaining), username))
        
        return remaining
    except Exception as e:
        print(f"WARNING: Failed to calculate remaining tests for reviewer '{username}': {e}")
        return []


def get_remaining_tests(db, username, user_id):
    """Get remaining tests, calculate if needed."""
    state = get_reviewer_state(db, username)
    remaining_tests = state['remaining_tests']
    
    if not remaining_tests:
        remaining_tests = calculate_and_update_remaining_tests(db, username, user_id)
    
    return remaining_tests

