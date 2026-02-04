import json
from flask import session
from review_modules import queries


def _upload_url(f):
    """Helper to build upload URL from filename."""
    if not f or not isinstance(f, str):
        return ""
    filename = f.split('/')[-1] if '/' in f else f
    if filename and len(filename) > 0 and not filename.startswith('FOREIGN') and not filename.startswith('['):
        return f"/jnd/api/review/upload/{filename}" + (".wav" if not filename.endswith('.wav') else "")
    return ""


def build_response(file_data, reviewed_count, played, absolute_file_num=None, total_files=None, db=None, user_id=None, subject_id=None, project=None, current_level=None):
    """Build JSON response with file URL, answer words, and metadata."""
    # file_data is always a dict from get_current_file_data()
    next_urls = {1: ""}
    
    if db and user_id is not None and subject_id and project and current_level is not None:
        try:
            files = queries.get_test_files(db, user_id, subject_id, project)
            if current_level + 1 < len(files):
                next_file = files[current_level + 1]
                next_filename = next_file.get('filename', '')
                next_url = _upload_url(next_filename) if next_filename else ""
                if next_url:
                    next_urls[1] = next_url
        except Exception:
            pass
    
    cur_filename = file_data.get('filename', '')
    cur_url = _upload_url(cur_filename) if cur_filename else ""
    
    file_id = file_data.get('id', 0)
    response = {
        "cur": cur_url, "next": next_urls,
        "answer": [file_data.get('answer', ''), ''], 
        "name": session.get("username", ""),
        "participant_id": file_data.get('participant_id', ''),
        "username": file_data.get('username', ''),
        "test": file_data.get('test', 'Unknown'),
        "list_number": file_data.get('list_number', 0),
        "level_number": file_data.get('level_number', 0),
        "position": reviewed_count,
        "review_count": file_data.get('review_count', 0),
        "already_played": file_id in played if file_id else False,
        "file_id": file_id
    }
    
    if absolute_file_num is not None and total_files is not None:
        response["current_file_num"] = absolute_file_num
        response["total_files"] = total_files
    
    return json.dumps(response)

