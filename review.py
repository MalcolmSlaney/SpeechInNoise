import json, os
from storage import DatabaseBP, relpath, Database
from flask import Blueprint, session, request, send_from_directory, abort, Response
from audio import upload_location
from review_modules.helpers import extract_username, save_review_annotation
from review_modules import state, queries, file_selection, responses

# Database configuration - change this to use a different database
# You can also set SELECTED_DATABASE environment variable to override this
SELECTED_DATABASE = os.environ.get("SELECTED_DATABASE", relpath("backup.db"))
REVIEW_SCHEMA = relpath("schema.sql")

def ensure_user_in_review_db(db, username, ip_address=None):
    """Make sure user exists in review DB, create if needed."""
    if not username:
        raise Exception("Username is required")
    
    labeler_result = db.queryone("SELECT id FROM users WHERE username = ?", (username,))
    
    if labeler_result:
        return labeler_result[0]
    
    ip = ip_address if ip_address else request.remote_addr if hasattr(request, 'remote_addr') else '0.0.0.0'
    
    try:
        user_id = db.execute(
            "INSERT INTO users (username, ip) VALUES (?, ?)",
            (username, ip))
        print(f"Created new user '{username}' in review database (ID: {user_id})")
        
        # url parameters from api.py
        if "meta" in session:
            try:
                db.execute(
                    "INSERT INTO user_info (user, info_key, value) "
                    "VALUES (?, 'searchParams', ?)",
                    (user_id, session["meta"]))
            except Exception:
                pass
        
        return user_id
    except Exception as e:
        labeler_result = db.queryone("SELECT id FROM users WHERE username = ?", (username,))
        if labeler_result:
            return labeler_result[0]
        raise Exception(f"Failed to create or find user '{username}' in review database: {e}")
    
    ######################## TODO: password protection? unique hash generation?


def review_start(db):
    try:
        username = extract_username()
        labeler_id = ensure_user_in_review_db(db, username, request.remote_addr)
        
        file_data, subject_id, project, current_level, total_files, absolute_file_num = file_selection.get_current_file_data(db, labeler_id, username)
        if not file_data:
            return json.dumps({"cur": "", "next": {1: ""}, "answer": ["", ""], "name": username})
        
        ref_id = file_data.get('id')
        if ref_id and not db.queryone("SELECT 1 FROM audio_results WHERE id = ?", (ref_id,)):
            raise Exception(f"audio_results.id={ref_id} does not exist in review database")
        
        reviewer_state = state.get_reviewer_state(db, username)
        return responses.build_response(file_data, reviewer_state['total_reviews'], reviewer_state['played_audio'], 
                            absolute_file_num, total_files, db, labeler_id, subject_id, project, current_level)
    except Exception as e:
        return json.dumps({"error": str(e), "cur": "", "next": {1: ""}, "answer": ["", ""], "name": session.get("username", "Unknown")})

def review_result(db):
    try: #validation, setup
        if "annotations" not in request.args: abort(400)
        
        username = extract_username()
        labeler_id = ensure_user_in_review_db(db, username, request.remote_addr)
        
        reviewer_state = state.get_reviewer_state(db, username)
        test_in_progress = reviewer_state['test_in_progress']
        if not test_in_progress:
            raise Exception("No test in progress - cannot save review")
        #save & format
        ref_id = test_in_progress["index"]
        
        try:
            annotations_list = json.loads(request.args["annotations"])
            annotations_str = json.dumps([bool(x) for x in annotations_list])
        except: 
            annotations_str = request.args["annotations"]
        
        unclear = request.args.get("unclear", "false").lower() in ("true", "1", "yes")
        
        try:
            save_review_annotation(db, ref_id, labeler_id, annotations_str, unclear)
        except Exception as e:
            error_msg = str(e)
            
            if "FOREIGN KEY" in error_msg or "constraint" in error_msg.lower():
                ref_exists = db.queryone("SELECT 1 FROM audio_results WHERE id = ?", (ref_id,))
                labeler_exists = db.queryone("SELECT 1 FROM users WHERE id = ?", (labeler_id,))
                fk_details = [
                    f"ref={ref_id} (audio_results.id) {'exists' if ref_exists else 'does NOT exist'}",
                    f"labeler={labeler_id} (users.id) {'exists' if labeler_exists else 'does NOT exist'}"
                ]
                detailed_error = f"Foreign key constraint failed: {', '.join(fk_details)}"
                
                existing = db.queryone("SELECT 1 FROM review_annotations WHERE ref = ? AND labeler = ?", (ref_id, labeler_id))
                if not existing:
                    raise Exception(detailed_error)
            else:
                existing = db.queryone("SELECT 1 FROM review_annotations WHERE ref = ? AND labeler = ?", (ref_id, labeler_id))
                if not existing:
                    raise e
        reviewed_file_info = db.queryone("""
            SELECT ar.subject, at.project 
            FROM audio_results ar
            LEFT JOIN audio_trials at ON ar.trial = at.id
            WHERE ar.id = ?
        """, (ref_id,))
        
        reviewed_subject_id = reviewed_file_info[0] if reviewed_file_info else None
        reviewed_project = reviewed_file_info[1] if reviewed_file_info else None
        #update
        state.remove_played_audio(db, username, ref_id)
        state.increment_total_reviews(db, username)
        #check success
        if reviewed_subject_id and reviewed_project and queries.is_test_complete(db, labeler_id, reviewed_subject_id, reviewed_project):
            state.add_completed_test(db, username, reviewed_subject_id, reviewed_project)
            state.update_most_recent_subject(db, username, reviewed_subject_id)
            reviewer_state = state.get_reviewer_state(db, username)
            remaining_tests = [t for t in reviewer_state['remaining_tests'] 
                             if (t["subject"], t["project"]) != (reviewed_subject_id, reviewed_project)]
            try:
                db.execute("UPDATE reviewers SET remaining_tests = ? WHERE username = ?",
                          (json.dumps(remaining_tests), username))
            except:
                pass
            state.clear_test_in_progress(db, username)
        #get next
        file_data, subject_id, project, current_level, total_files, absolute_file_num = file_selection.get_current_file_data(db, labeler_id, username)
        if not file_data:
            return json.dumps({"cur": "", "next": {1: ""}, "answer": ["", ""], "name": username})
        
        files_reviewed = queries.get_files_reviewed_in_test(db, labeler_id, subject_id, project)
        absolute_file_num = files_reviewed + 1
        state.update_test_in_progress(db, username, subject_id, project, file_data['id'], total_files, files_reviewed, absolute_file_num)
        #return
        reviewer_state = state.get_reviewer_state(db, username)
        return responses.build_response(file_data, reviewer_state['total_reviews'], reviewer_state['played_audio'], 
                            absolute_file_num, total_files, db, labeler_id, subject_id, project, current_level)
    except Exception as e:
        error_msg = str(e)
        return json.dumps({"error": error_msg, "cur": "", "next": {1: ""}, "answer": ["", ""], "name": session.get("username", "Unknown")})

def review_reset(db):
    """Reset session and log out user. Progress is preserved in database."""
    try:
        # Clear the entire session to fully log out the user
        session.clear()
        # Also mark session as modified to ensure cookie is cleared
        session.permanent = False
        return json.dumps({"status": "success"})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

def track_audio_played(db):
    """Track that audio was played (for reminder if not reviewed)."""
    try:
        username = session.get("username") or request.args.get("username")
        if not username:
            abort(400)
        
        file_id = request.args.get("file_id") or request.json.get("file_id") if request.is_json else None
        if not file_id:
            try:
                file_id = int(request.args.get("ref") or (request.json.get("ref") if request.is_json else None))
            except:
                abort(400)
        
        state.add_played_audio(db, username, file_id)
        
        return json.dumps({"status": "success"})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

def review_index(db): 
    return send_from_directory(relpath("static"), "review_index.html")


class ReviewBP(DatabaseBP):
    def __init__(self, db, name="review", url_prefix="/review"):
        # Use different DB than parent, so init Blueprint directly
        Blueprint.__init__(self, name, __name__, url_prefix=url_prefix)
        self._route_db("/")(review_index)
        self._route_db("/start")(review_start)
        self._route_db("/result", methods=["POST", "GET"])(review_result)
        self._route_db("/reset", methods=["POST"])(review_reset)
        self._route_db("/track-played", methods=["POST", "GET"])(track_audio_played)
        self._route_db("/upload/<fname>")(self.upload)
        def handle_review_review(db): return Response(status=204)
        self._route_db("/review")(handle_review_review)
        self.record(lambda setup: self._bind_db(setup.app))
        self._fallback_db = db
        self._blueprint_db = None
    
    def _bind_db(self, app):
        try:
            self._blueprint_db = Database(app, SELECTED_DATABASE, REVIEW_SCHEMA, ["PRAGMA foreign_keys = ON"])
        except Exception:
            raise
    
    def _route_db(self, *a, **kw):
        from functools import wraps
        from flask import jsonify
        def wrapper(f):
            @wraps(f)
            def wrapped(*ra, **kra):
                if not hasattr(self, '_blueprint_db') or self._blueprint_db is None:
                    return jsonify({
                        "error": "Review database not initialized.",
                        "cur": "",
                        "next": {1: ""},
                        "answer": ["", ""],
                        "name": "Unknown"
                    }), 500
                return f(self._blueprint_db, *ra, **kra)
            return self.route(*a, **kw)(wrapped)
        return wrapper
    
    def audio_lists(self, db): return "[]"
    def upload(self, db, fname): return send_from_directory(upload_location, fname)
