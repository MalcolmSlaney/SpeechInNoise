import json
from flask import session
from review_modules.helpers import upload_url
from review_modules import queries


def build_response(file_data, reviewed_count, played, absolute_file_num=None, total_files=None, db=None, user_id=None, subject_id=None, project=None, current_level=None):
    """Build JSON response with file URL, answer words, and metadata."""
    next_urls = {1: ""}
    
    if db and user_id is not None and subject_id and project and current_level is not None:
        try:
            files = queries.get_test_files(db, user_id, subject_id, project)
            if current_level + 1 < len(files):
                next_file = files[current_level + 1]
                next_filename = next_file.get('filename', '') if isinstance(next_file, dict) else ''
                next_url = upload_url(next_filename) if next_filename and isinstance(next_filename, str) else ""
                if next_url:
                    next_urls[1] = next_url
        except Exception as e:
            print(f"WARNING: Could not determine next file URL: {e}")
    
    cur_filename = file_data.get('filename', '') if isinstance(file_data, dict) else ''
    cur_url = upload_url(cur_filename) if cur_filename and isinstance(cur_filename, str) else ""
    
    file_id = file_data.get('id', 0) if isinstance(file_data, dict) else 0
    response = {
        "cur": cur_url, "next": next_urls,
        "answer": [file_data.get('answer', '') if isinstance(file_data, dict) else '', ''], 
        "name": session.get("username", ""),
        "participant_id": file_data.get('participant_id', '') if isinstance(file_data, dict) else '',
        "username": file_data.get('username', '') if isinstance(file_data, dict) else '',
        "test": file_data.get('test', 'Unknown') if isinstance(file_data, dict) else 'Unknown',
        "list_number": file_data.get('list_number', 0) if isinstance(file_data, dict) else 0,
        "level_number": file_data.get('level_number', 0) if isinstance(file_data, dict) else 0,
        "position": reviewed_count,
        "review_count": file_data.get('review_count', 0) if isinstance(file_data, dict) else 0,
        "already_played": file_id in played if file_id else False,
        "file_id": file_id
    }
    
    if absolute_file_num is not None and total_files is not None:
        response["current_file_num"] = absolute_file_num
        response["total_files"] = total_files
    
    return json.dumps(response)

