from flask import session, request, abort

def extract_username():
    username = session.get("username") or request.args.get("username")
    if not username:
        if "user" not in session:
            abort(400)
        username = session.get("username", "")
        if not username:
            raise Exception("No username provided")
    username = username.lower() if username else username
    if not session.get("username"):
        session["username"] = username
    return username


def save_review_annotation(db, ref_id, labeler_id, annotations_str, unclear):
    # Verify foreign keys exist before inserting
    ref_exists = db.queryone("SELECT 1 FROM audio_results WHERE id = ?", (ref_id,))
    labeler_exists = db.queryone("SELECT 1 FROM users WHERE id = ?", (labeler_id,))
    if not ref_exists or not labeler_exists:
        error_parts = [f"ref={ref_id} exists={bool(ref_exists)}", f"labeler={labeler_id} exists={bool(labeler_exists)}"]
        if hasattr(db, 'database'):
            error_parts.append(f"database={db.database}")
        raise Exception(f"Foreign key constraint failed: {' | '.join(error_parts)}")
    
    db.execute("PRAGMA foreign_keys = ON")
    
    existing = db.queryone("SELECT 1 FROM review_annotations WHERE ref = ? AND labeler = ?", (ref_id, labeler_id))
    
    try:
        columns = db.queryall("PRAGMA table_info(review_annotations)")
        has_unclear_column = any(col[1] == 'unclear' for col in columns)
    except:
        has_unclear_column = False
    
    if existing:
        if has_unclear_column:
            db.execute("UPDATE review_annotations SET data = ?, unclear = ? WHERE ref = ? AND labeler = ?",
                      (annotations_str, 1 if unclear else 0, ref_id, labeler_id))
        else:
            db.execute("UPDATE review_annotations SET data = ? WHERE ref = ? AND labeler = ?",
                      (annotations_str, ref_id, labeler_id))
    else:
        if has_unclear_column:
            db.execute("INSERT INTO review_annotations (ref, data, labeler, unclear) VALUES (?, ?, ?, ?)",
                      (ref_id, annotations_str, labeler_id, 1 if unclear else 0))
        else:
            db.execute("INSERT INTO review_annotations (ref, data, labeler) VALUES (?, ?, ?)",
                      (ref_id, annotations_str, labeler_id))

