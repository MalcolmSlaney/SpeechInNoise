"""Automates the scoring of ASR results and generates audiology comparison reports.

This script evaluates machine-transcribed speech against ground-truth answers stored
in an SQLite database. It resolves valid variations using both inline options ('/') 
and an external homonyms dictionary. 

It performs two main actions:
1. Updates the database with new correct_word_count and gt_word_count metrics.
2. Compares the ASR matches against human audiologist judgements (audio_annotations)
   to generate a CSV export, confusion matrices, an HTML discrepancy report, and 
   a terminal summary.

To measure coverage:
  coverage run score_and_report_test.py
  coverage report -m --include=score_and_report.py
"""

import sqlite3
import json
import re
import csv
import os
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, Set, List, Optional, Tuple, Any, Union

import numpy as np
from numpy.typing import ArrayLike, NDArray
import matplotlib.pyplot as plt
from absl import app
from absl import flags
from absl import logging

FLAGS = flags.FLAGS

# Define command-line flags
try:
  flags.DEFINE_string('dbfile', 'experiments_malcolm.db', 'Path to the SQLite database.')
except flags.DuplicateFlagError:
  pass # Flag was already defined by another module during pytest collection
flags.DEFINE_string('homonyms', 'homonym_list.csv', 'Path to the comma-delimited homonyms file.')
flags.DEFINE_string('discrepancies', 'asr_audiology_discrepancies.html', 'Where to store the final discrepancy report.')
flags.DEFINE_bool('only_foreign', False, 'Whether to only show foreign recognizer results in discrepancies html')
flags.DEFINE_bool('only_discrepancies', True, 'Whether to only show human/machine discrepancies the final html')
flags.DEFINE_string('subject_filter', 'A\\d+[SP]\\d+', 'Regex to filter which subjects to include in the analysis.')


@dataclass
class QS_result:
    """Dataclass containing everything retrieved from the web database to describe one trial.
    Must perfectly align with the explicit SQL query (now 29 columns).
    """
    results_id: int
    results_subject: int
    results_trial: int
    results_reply_filename: str
    results_time: str              
    trials_id: int
    trials_project: str            
    trials_snr: int
    trials_lang: str
    trials_level_number: int 
    trials_trial_number: int 
    trials_filename: str 
    trials_answer: str 
    trials_active: bool  
    user_id: int
    user_name: str 
    user_ip: str
    user_time: str 
    user_info_id: int
    user_info_key: str 
    user_info_value: str
    user_info_time: str
    asr_id: int
    asr_results: Union[str, Dict[str, Any]]
    # NEW: The 3 scoring columns added to the database schema
    asr_gt_word_count: Optional[int]
    asr_correct_word_count: Optional[int]
    asr_clean_tokens: Optional[str]
    # Back to annotations:
    annotation_ref: int
    annotation_matches: Union[str, List[bool]] 
    # Constructed dynamically during scoring:
    asr_words: Optional[List[str]] = None  
    asr_matches: Optional[List[bool]] = None 
    asr_times: Optional[List[float]] = None 
    audiology_asr_matches: Optional[List[bool]] = None


def load_homonyms(filepath: str) -> Dict[str, Set[str]]:
    """Reads a comma-delimited file of homonyms."""
    homonym_map: Dict[str, Set[str]] = {}
    try:
        with open(filepath, 'r') as f:
            for line in f:
                if line.startswith('#'): continue
                line = line.split('#', 1)[0].rstrip()
                words = [w.strip() for w in line.strip().lower().split(',')]
                words = [w for w in words if w]
                if not words: continue
                word_set = set(words)
                for w in words:
                    homonym_map[w] = word_set
        logging.info(f"Loaded homonyms from {filepath}")
    except FileNotFoundError:
        logging.warning(f"Homonyms file '{filepath}' not found. Proceeding with exact matches only.")
    return homonym_map


def clean_and_tokenize(text: Optional[str]) -> Set[str]:
    """Lowercases text, removes punctuation, and extracts unique words."""
    if not text:
        return set()
    clean_text = re.sub(r'[^\w\s]', '', text).lower()
    return set(clean_text.split())


def fix_random_user_names(text_tag: str) -> str:
    match text_tag:
        case 'DFe3RNee' | 'NQE7QNNm': return 'A0S1'
        case 'mMD4mHfH': return 'A0S2'
        case 'QA7D33Nr': return 'A0S3'
    return text_tag


def fix_encoding(bad_string: str) -> str:
    try:
        fixed_string = bad_string.encode('cp1252').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        fixed_string = bad_string
    html_encoded = fixed_string.encode('ascii', 'xmlcharrefreplace').decode('ascii')
    return html_encoded


def save_results_as_csv(all_results: List[QS_result], csv_file: str = 'quicksin_results.csv') -> str:
    """Exports the processed results to a CSV file."""
    header = [
        'results_id', 'results_subject', 'results_trial', 'results_reply_filename',
        'results_time', 'trials_id', 'trials_project', 'trials_snr', 'trials_lang',
        'trials_level_number', 'trials_trial_number', 'trials_filename',
        'trials_answer', 'trials_active', 'user_id', 'user_name', 'user_ip',
        'user_time', 'user_info_id', 'user_info_key', 'user_info_value',
        'user_info_time', 'asr_id', 'asr_results', 
        # NEW: Added headers for the export
        'asr_gt_word_count', 'asr_correct_word_count', 'asr_clean_tokens',
        'annotation_ref', 'annotation_matches', 'asr_words', 'asr_matches', 
        'asr_times', 'audiology_asr_matches'
    ]

    with open(csv_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for result in all_results:
            row_data = [
                result.results_id, result.results_subject, result.results_trial,
                result.results_reply_filename, result.results_time,
                result.trials_id, result.trials_project, result.trials_snr,
                result.trials_lang, result.trials_level_number,
                result.trials_trial_number, result.trials_filename,
                result.trials_answer,
                result.trials_active, result.user_id, result.user_name, result.user_ip,
                result.user_time, result.user_info_id, result.user_info_key,
                result.user_info_value, result.user_info_time, result.asr_id,
                json.dumps(result.asr_results), 
                # NEW: Extracting the scoring data for the row
                result.asr_gt_word_count, result.asr_correct_word_count, result.asr_clean_tokens,
                result.annotation_ref,
                json.dumps(result.annotation_matches),
                ','.join(result.asr_words) if result.asr_words else '',
                ','.join([str(m) for m in result.asr_matches]) if result.asr_matches else '',
                ','.join([str(t) for t in result.asr_times]) if result.asr_times else '',
                ','.join([str(m) for m in result.audiology_asr_matches]) if result.audiology_asr_matches else ''
            ]
            writer.writerow(row_data)

    logging.info(f'Results written to {csv_file}')
    return csv_file


def accumulate_errors(sum_arr: NDArray, human: ArrayLike, asr: ArrayLike) -> None:
    assert sum_arr.ndim == 2
    assert sum_arr.shape == (2, 2)
    for h, a in zip(human, asr):
        sum_arr[int(h), int(a)] += 1


def all_test_confusions(all_results: List[QS_result], valid_subject_re: re.Pattern) -> Dict[str, NDArray]:
    all_confusions = {}
    for r in all_results:
        if valid_subject_re.match(r.user_name):
            if r.annotation_matches and r.asr_matches and len(r.annotation_matches) == len(r.asr_matches):
                test_name = r.trials_project
                if test_name not in all_confusions:
                    all_confusions[test_name] = np.zeros((2, 2), dtype=int)
                accumulate_errors(all_confusions[test_name], r.annotation_matches, r.asr_matches)
    return all_confusions


def plot_confusions(all_confusions: Dict[str, NDArray]):
    centers = [0, 1]
    plt.figure(figsize=(10, 6))
    for i, test_name in enumerate(all_confusions.keys()):
        if i >= 6: break
        plt.subplot(2, 3, i+1)
        confusions = all_confusions[test_name]
        plt.imshow(confusions)
        for human_match in [0, 1]:
            for asr_match in [0, 1]:
                plt.text(centers[human_match], centers[asr_match], 
                        confusions[human_match, asr_match],
                        ha="center", va="center", color="w")
        plt.title(test_name)
        if i == 0 or i == 3:
            plt.ylabel('Human')
            plt.yticks([0, 1], ['False', 'True'])
        else:
            plt.yticks([])
        if i >= 3:
            plt.xlabel('ASR')
            plt.xticks([0, 1], ['False', 'True'])
        else:
            plt.xticks([])
    plt.tight_layout()
    plt.savefig('confusion_matrices.png')
    logging.info('Saved confusion_matrices.png')


def generate_html_report(all_results: List[QS_result], db_file: str, 
                         only_discrepancies: bool, only_foreign: bool, 
                         valid_subject_re: re.Pattern, max_number: int = 10000) -> Tuple[str, int]:
    
    current_time = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
    db_mod_time = "Unknown"
    if os.path.exists(db_file):
        mtime = os.path.getmtime(db_file)
        db_mod_time = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %I:%M:%S %p")
    
    html_output = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <title>Online SPIN Test vs Audiologist Discrepancies</title>
    <style>
      table {{ border-collapse: collapse; width: 100%; }}
      th, td {{ border: 1px solid #dddddd; text-align: left; padding: 8px; }}
      th {{ background-color: #f2f2f2; }}
      .discrepancy {{ background-color: #ffcccc; }}
    </style>
    </head>
    <body>
    <h1>QuickSIN ASR vs Audiologist Discrepancies</h1>
    <p><strong>Report Generated:</strong> {current_time}</p>
    <p><strong>Database Last Modified:</strong> {db_mod_time} <em>({os.path.basename(db_file)})</em></p>
    <table>
      <tr>
        <th>Subject</th>
        <th>Test Type</th>
        <th>List Number</th>
        <th>Sentence Number</th>
        <th>Ground Truth</th>
        <th>ASR Words</th>
        <th>Audiologist Matches</th>
        <th>ASR Matches</th>
        <th>Agree</th>
        <th>Subject Audio</th>
      </tr>
    """

    row_count = 0
    for result in all_results[:max_number]:
        if not valid_subject_re.match(result.user_name): continue
        if not result.annotation_matches or not result.asr_matches: continue
        
        # Discrepancy check
        if only_discrepancies and result.annotation_matches == result.asr_matches: continue

        # Foreign check
        if only_foreign and result.asr_words and all([r.isascii() for r in result.asr_words]): continue
        
        html_output += "<tr>"
        html_output += f"<td>{result.user_name}</td>"
        html_output += f"<td>{result.trials_project}</td>"
        html_output += f"<td>{result.trials_trial_number}</td>"
        html_output += f"<td>{result.trials_level_number}</td>"
        html_output += f"<td>{result.trials_answer}</td>"
        html_output += f"<td>{', '.join([fix_encoding(r) for r in result.asr_words]) if result.asr_words else 'N/A'}</td>"
        html_output += f"<td>{result.annotation_matches}</td>"
        html_output += f"<td>{result.asr_matches}</td>"
        
        if result.audiology_asr_matches and all(result.audiology_asr_matches):
            html_output += "<td>&#9989;</td>" 
        else:
            html_output += "<td>&#10008;</td>" 
            
        audio_url = f"https://quicksin.stanford.edu/uploads/{result.results_reply_filename}.wav"
        html_output += f'<td><audio controls> <source src={audio_url} type=audio/mp4>Your browser does not support the audio element.</audio></td>'
        html_output += "</tr>\n"
        row_count += 1

    html_output += "</table></body></html>"
    return html_output, row_count


def main(argv: List[str]) -> None:
    del argv  # Unused

    assert os.path.exists(FLAGS.dbfile), f'Database file {FLAGS.dbfile} does not exist.'

    # 1. Load the homonyms dictionary
    homonyms_map = load_homonyms(FLAGS.homonyms)

    # 2. Connect to the database
    conn = sqlite3.connect(FLAGS.dbfile)
    cursor = conn.cursor()

    # 3. Explicit Column Selection (Now including the 3 new scoring metrics)
    query = """
        SELECT 
          audio_results.id, audio_results.subject, audio_results.trial, audio_results.reply_filename, audio_results.t,
          audio_trials.id, audio_trials.project, audio_trials.snr, audio_trials.lang, audio_trials.level_number, audio_trials.trial_number, audio_trials.filename, audio_trials.answer, audio_trials.active,
          users.id, users.username, users.ip, users.t,
          user_info.user, user_info.info_key, user_info.value, user_info.t,
          audio_asr.ref, audio_asr.data, audio_asr.gt_word_count, audio_asr.correct_word_count, audio_asr.asr_clean_tokens,
          audio_annotations.ref, audio_annotations.data
        FROM audio_results
        LEFT JOIN audio_trials ON audio_results.trial=audio_trials.id
        LEFT JOIN users ON audio_results.subject=users.id
        LEFT JOIN (select * from user_info where info_key='test-type' group by user) as 'user_info' ON users.id=user_info.user
        LEFT JOIN audio_asr ON audio_results.id=audio_asr.ref
        LEFT JOIN audio_annotations ON audio_results.id=audio_annotations.ref
        WHERE user_info.info_key='test-type'
    """
    cursor.execute(query)
    raw_rows = cursor.fetchall()

    updates: List[tuple] = []
    all_results: List[QS_result] = []
    
    # 4. Process each trial for scoring AND reporting
    for row in raw_rows:
        a_result = QS_result(*row)
        
        # Cleanup routine
        a_result.user_name = fix_random_user_names(a_result.user_name)
        if a_result.user_name in ['A1P8', 'A1P9', 'A2P15']:
            continue # Skip bad direction followers
            
        if not a_result.asr_results or not a_result.trials_answer:
            continue

        # Parse JSON blocks
        try:
            a_result.asr_results = json.loads(a_result.asr_results)
            asr_text = a_result.asr_results.get('text', '')
        except json.JSONDecodeError:
            logging.error(f"Invalid ASR JSON found for ref {a_result.asr_id}. Skipping.")
            continue

        if isinstance(a_result.annotation_matches, str):
            try:
                a_result.annotation_matches = json.loads(a_result.annotation_matches)
            except json.JSONDecodeError:
                a_result.annotation_matches = []

        # Extract words for reporting
        a_result.asr_words = []
        a_result.asr_times = []
        if (a_result.asr_results and 'segments' in a_result.asr_results and
            a_result.asr_results['segments'] and 'words' in a_result.asr_results['segments'][0]):
            a_result.asr_words = [w['word'] for w in a_result.asr_results['segments'][0]['words']]
            a_result.asr_times = [w.get('start', 0.0) for w in a_result.asr_results['segments'][0]['words']]

        # 5. Core Scoring Logic
        asr_tokens = clean_and_tokenize(asr_text)
        asr_tokens_str = ",".join(sorted(asr_tokens))
        
        gt_slots = a_result.trials_answer.split()
        gt_word_count = len(gt_slots)
        correct_word_count = 0
        a_result.asr_matches = []

        for gt_slot in gt_slots:
            slot_options = gt_slot.split('/')
            acceptable_words: Set[str] = set()
            
            for option in slot_options:
                clean_option = re.sub(r'[^\w\s]', '', option).lower()
                if clean_option:
                    acceptable_words.update(homonyms_map.get(clean_option, {clean_option}))

            if not acceptable_words:
                a_result.asr_matches.append(False)
                continue

            match = bool(acceptable_words.intersection(asr_tokens))
            a_result.asr_matches.append(match)
            if match:
                correct_word_count += 1
                
        # Since we are scoring on the fly, immediately assign the calculated values to the dataclass
        # so they get written out to the CSV correctly
        a_result.asr_gt_word_count = gt_word_count
        a_result.asr_correct_word_count = correct_word_count
        a_result.asr_clean_tokens = asr_tokens_str

        # Calculate Audilogy vs ASR Agreement
        if a_result.annotation_matches and len(a_result.annotation_matches) == len(a_result.asr_matches):
            a_result.audiology_asr_matches = [not(a ^ b) for a, b in zip(a_result.asr_matches, a_result.annotation_matches)]
        else:
            a_result.audiology_asr_matches = []

        updates.append((gt_word_count, correct_word_count, asr_tokens_str, a_result.asr_id))
        all_results.append(a_result)

    # 6. Database Update
    if updates:
        update_query = """
            UPDATE audio_asr 
            SET gt_word_count = ?, correct_word_count = ?, asr_clean_tokens = ? 
            WHERE ref = ?
        """
        cursor.executemany(update_query, updates)
        conn.commit()
        logging.info(f"Successfully processed and updated {len(updates)} records in DB.")

    conn.close()

    # 7. Generate All Reports
    print("\n--- Generating Reports ---")
    valid_subject_re = re.compile(FLAGS.subject_filter)
    
    # CSV
    save_results_as_csv(all_results, 'quicksin_results.csv')

    # Confusion Matrices
    all_confusions = all_test_confusions(all_results, valid_subject_re=valid_subject_re)
    plot_confusions(all_confusions)

    # HTML Report
    html_report, row_count = generate_html_report(
        all_results, 
        db_file=FLAGS.dbfile,  
        only_discrepancies=FLAGS.only_discrepancies,
        only_foreign=FLAGS.only_foreign,
        valid_subject_re=valid_subject_re
    )
    with open(FLAGS.discrepancies, 'w') as f:
        f.write(html_report)
    print(f'Wrote {row_count} discrepancy rows to {FLAGS.discrepancies}')

    # Terminal Summary
    total_tests = 0
    total_correct = 0
    print('\nTest accuracies (ASR vs Human Agreement):')
    for test, results in all_confusions.items():
        num_tests = np.sum(results)
        if num_tests > 0:
            num_correct = results[0,0] + results[1,1]
            total_tests += num_tests
            total_correct += num_correct
            print(f'{test}: {num_correct/num_tests*100:.2f}%')
    if total_tests > 0:
        print(f'Overall: {total_correct/total_tests*100:.2f}%')
    else:
        print('No valid comparison data found for summary.')


if __name__ == '__main__':
    app.run(main)
