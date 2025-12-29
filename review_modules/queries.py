import os

def get_available_tests(db, user_id):
    return db.queryall("""
        SELECT ar.subject, at.project, COUNT(DISTINCT CASE WHEN ui_labeler.info_key = 'test-type' AND ui_labeler.value = 'patient' THEN ra.ref ELSE NULL END) as total_reviews
        FROM audio_results ar
        LEFT JOIN audio_trials at ON ar.trial = at.id
        LEFT JOIN users u ON ar.subject = u.id
        LEFT JOIN user_info ui ON u.id = ui.user
        LEFT JOIN review_annotations ra ON ar.id = ra.ref
        LEFT JOIN users u_labeler ON ra.labeler = u_labeler.id
        LEFT JOIN user_info ui_labeler ON u_labeler.id = ui_labeler.user AND ui_labeler.info_key = 'test-type'
        WHERE ui.info_key = 'test-type' AND ui.value = 'patient'
        AND ar.id NOT IN (SELECT ref FROM review_annotations WHERE labeler = ?)
        AND EXISTS (SELECT 1 FROM audio_results ar2 
                    LEFT JOIN audio_trials at2 ON ar2.trial = at2.id
                    WHERE ar2.subject = ar.subject AND at2.project = at.project
                    AND ar2.id NOT IN (SELECT ref FROM review_annotations WHERE labeler = ?))
        GROUP BY ar.subject, at.project
        ORDER BY total_reviews ASC, ar.subject ASC, at.project ASC
    """, (user_id, user_id))

def get_test_files(db, user_id, subject_id, project):
    try:
        results = db.queryall("""
            SELECT ar.id, ar.reply_filename, ar.subject, ar.trial, at.answer,
                   at.project, at.trial_number, at.level_number,
                   COUNT(CASE WHEN ui_labeler.info_key = 'test-type' AND ui_labeler.value = 'patient' THEN ra.ref ELSE NULL END) as review_count, u.username
            FROM audio_results ar
            LEFT JOIN audio_trials at ON ar.trial = at.id
            LEFT JOIN review_annotations ra ON ar.id = ra.ref
            LEFT JOIN users u_labeler ON ra.labeler = u_labeler.id
            LEFT JOIN user_info ui_labeler ON u_labeler.id = ui_labeler.user AND ui_labeler.info_key = 'test-type'
            LEFT JOIN users u ON ar.subject = u.id
            WHERE ar.subject = ? AND at.project = ?
            AND ar.id NOT IN (SELECT ref FROM review_annotations WHERE labeler = ?)
            GROUP BY ar.id
            ORDER BY at.trial_number ASC, at.level_number ASC
        """, (subject_id, project, user_id))
        return [{'id': r[0],
                'filename': r[1] if r[1] and isinstance(r[1], str) else '',
                'answer': r[4] or '' if r[4] else '',          
                'participant_id': r[2],
                'username': r[9] if r[9] else '',
                'test': r[5] or 'Unknown',
                'list_number': r[6] or 0,
                'level_number': r[7] or 0,
                'review_count': r[8]} for r in results
                if r[1] and isinstance(r[1], str) and os.path.exists(f"/var/www/jnd/uploads/{r[1]}")]
    except Exception as e:
        print(f"ERROR in get_test_files: {e}")
        import traceback
        traceback.print_exc()
        return []

def get_total_test_files(db, subject_id, project):
    try:
        result = db.queryall("""
            SELECT ar.id, ar.reply_filename
            FROM audio_results ar
            LEFT JOIN audio_trials at ON ar.trial = at.id
            WHERE ar.subject = ? AND at.project = ?
            AND ar.reply_filename IS NOT NULL 
            AND ar.reply_filename != ''
        """, (subject_id, project))
        return sum(1 for r in result 
                   if r[1] and isinstance(r[1], str) 
                   and os.path.exists(f"/var/www/jnd/uploads/{r[1]}"))
    except Exception as e:
        print(f"ERROR in get_total_test_files: {e}")
        import traceback
        traceback.print_exc()
        return 0

def get_files_reviewed_in_test(db, user_id, subject_id, project):
    try:
        result = db.queryone("""
            SELECT COUNT(DISTINCT ra.ref)
            FROM review_annotations ra
            INNER JOIN audio_results ar ON ra.ref = ar.id
            INNER JOIN audio_trials at ON ar.trial = at.id
            WHERE ra.labeler = ? 
            AND ar.subject = ? 
            AND at.project = ?
        """, (user_id, subject_id, project))
        return result[0] if result else 0
    except Exception as e:
        print(f"ERROR in get_files_reviewed_in_test: {e}")
        import traceback
        traceback.print_exc()
        return 0

def is_test_complete(db, user_id, subject_id, project):
    try:
        total_files = get_total_test_files(db, subject_id, project)
        if total_files == 0:
            return False
        return get_files_reviewed_in_test(db, user_id, subject_id, project) >= total_files
    except Exception as e:
        print(f"WARNING: Failed to check if test is complete: {e}")
        return False

