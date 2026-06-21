# Obsolete !!!   Replaced by score_and_report which also creates the necessary reports.

"""Automates the scoring of ASR (Automatic Speech Recognition) results for speech-in-noise trials.

This script evaluates machine-transcribed speech against ground-truth answers stored
in an SQLite database. It is designed to support auditory research and speech recognition 
testing by robustly handling spoken text variations. It cleans and tokenizes both the ASR 
output and the expected answers, resolving valid variations using both inline options 
(separated by '/') in the ground truth and an external, comma-delimited homonyms dictionary. 

The script calculates the total number of expected words and the number of correctly 
identified words for each trial, then updates the database with these metrics along 
with the cleaned ASR tokens.
"""

import sqlite3
import json
import re
from typing import Dict, Set, List, Optional
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

def load_homonyms(filepath: str) -> Dict[str, Set[str]]:
    """Reads a comma-delimited file of homonyms.

    Args:
        filepath (str): The path to the comma-delimited homonyms file.

    Returns:
        Dict[str, Set[str]]: A dictionary where each key is a word (str) and its value is a 
            set of its homonyms (including the word itself). Returns an empty 
            dictionary if the file is not found.
    """
    homonym_map: Dict[str, Set[str]] = {}
    try:
        with open(filepath, 'r') as f:
            for line in f:
                # Lowercase, split by comma, and strip any surrounding whitespace
                words = [w.strip() for w in line.strip().lower().split(',')]
                
                # Filter out any empty strings (e.g., from a trailing comma)
                words = [w for w in words if w]
                
                if not words:
                    continue
                
                word_set = set(words)
                # Map every word in the group to the entire group of homonyms
                for w in words:
                    homonym_map[w] = word_set
        logging.info(f"Loaded homonyms from {filepath}")
    except FileNotFoundError:
        logging.warning(f"Homonyms file '{filepath}' not found. Proceeding with exact matches only.")
    
    return homonym_map

def clean_and_tokenize(text: Optional[str]) -> Set[str]:
    """Lowercases text, removes punctuation, and extracts unique words.

    Args:
        text (Optional[str]): The input text string to be cleaned and tokenized.

    Returns:
        Set[str]: A set of unique, lowercase words with all punctuation removed. 
            Returns an empty set if the input text is None or empty.
    """
    if not text:
        return set()
    clean_text = re.sub(r'[^\w\s]', '', text).lower()
    return set(clean_text.split())

def main(argv: List[str]) -> None:
    """Executes the ASR scoring pipeline.

    Connects to the specified SQLite database, evaluates the JSON ASR text against 
    ground truth answers using homonym matching (both via external file and inline 
    '/' separators), and updates the database with the resulting word counts and 
    the cleaned ASR tokens.

    Args:
        argv (List[str]): Command-line arguments passed to the script. Unused in 
            this function as configuration is handled via absl flags.

    Returns:
        None
    """
    del argv  # Unused

    # 1. Load the homonyms dictionary
    homonyms_map = load_homonyms(FLAGS.homonyms)

    # 2. Connect to the database
    conn = sqlite3.connect(FLAGS.dbfile)
    cursor = conn.cursor()

    # 3. Fetch the necessary data using a JOIN across the three tables
    query = """
        SELECT a.ref, a.data, t.answer
        FROM audio_asr a
        JOIN audio_results r ON a.ref = r.id
        JOIN audio_trials t ON r.trial = t.id
    """
    cursor.execute(query)
    rows = cursor.fetchall()

    updates: List[tuple] = []
    
    # 4. Process each trial
    for ref, data_json, answer in rows:
        if not data_json or not answer:
            continue

        # Parse the JSON ASR data
        try:
            asr_data = json.loads(data_json)
            asr_text = asr_data.get('text', '')
        except json.JSONDecodeError:
            logging.error(f"Invalid JSON found for audio_asr.ref {ref}. Skipping.")
            continue

        # Tokenize the ASR text into a set of words for fast lookup
        asr_tokens = clean_and_tokenize(asr_text)
        
        # Convert the set of tokens into a comma-separated string for database storage
        asr_tokens_str = ",".join(sorted(asr_tokens))

        # Process the ground truth answer
        # Splitting by whitespace to get individual word "slots"
        gt_slots = answer.split()
        gt_word_count = len(gt_slots)
        correct_word_count = 0

        for gt_slot in gt_slots:
            # Split the slot by '/' to handle inline homonyms/options
            slot_options = gt_slot.split('/')
            
            acceptable_words: Set[str] = set()
            
            # Clean each option and fetch its homonyms
            for option in slot_options:
                clean_option = re.sub(r'[^\w\s]', '', option).lower()
                if clean_option:
                    # Add the cleaned option and any known homonyms from the CSV
                    acceptable_words.update(homonyms_map.get(clean_option, {clean_option}))

            # If the slot ended up empty after cleaning, skip it
            if not acceptable_words:
                continue

            # Check if an intersection exists between acceptable words and ASR tokens
            if acceptable_words.intersection(asr_tokens):
                correct_word_count += 1

        # Store the calculated values for a batch update
        updates.append((gt_word_count, correct_word_count, asr_tokens_str, ref))

    # 5. Apply updates back to the database
    if updates:
        update_query = """
            UPDATE audio_asr 
            SET gt_word_count = ?, correct_word_count = ?, asr_clean_tokens = ? 
            WHERE ref = ?
        """
        cursor.executemany(update_query, updates)
        conn.commit()
        logging.info(f"Successfully processed and updated {len(updates)} records.")
    else:
        logging.info("No records to update.")

    conn.close()

if __name__ == '__main__':
    app.run(main)