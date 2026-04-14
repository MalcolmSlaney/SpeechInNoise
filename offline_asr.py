"""
Run ASR on all the subject audio that has not already been processed.
Store the results in the audio_asr table as Whisper's JSON.
The only output from this program is an update datbase file.
"""
import copy
from datetime import datetime
import json
import os
import pathlib
import pprint
import scipy.io.wavfile
import sqlite3
import subprocess
import sys
import tempfile
from tqdm import tqdm
from typing import Any, Dict, List, Optional, Tuple
from multiprocessing import Pool
from functools import partial

import asr

default_sample_rate = 22050
basename = pathlib.Path(__file__).parents[0]

#################### Audio Processing Functions ####################

def get_wav_duration_seconds(file_path: str) -> float:
  """
  Reads a WAV file and returns its length in seconds.
  """
  try:
    samplerate, data = scipy.io.wavfile.read(file_path)
    duration = len(data) / samplerate
    return duration
  except FileNotFoundError:
    print(f"Error: File not found at {file_path}")
    return -1.0
  except Exception as e:
    print(f"An error occurred while processing {file_path}: {e}")
    return -1.0


def concatenate_audio_files(input_file1: str, input_file2: str) -> str:
  """
  Concatenates two audio files using ffmpeg, saves the result to a temporary WAV file,
  and returns the filename of the temporary output.
  """
  temp_output_filename = tempfile.mktemp(suffix='.wav')

  cmd = ('ffmpeg -i {} -i {} -filter_complex '
         '"[0:a]aresample={}[a0];[1:a]aresample={}[a1];'
         '[a0][a1]concat=n=2:v=0:a=1[out]" -map "[out]" {}')
  formatted_cmd = cmd.format(input_file1, input_file2, 22050, 22050, temp_output_filename)

  process = subprocess.run(formatted_cmd, shell=True, capture_output=True, text=True)

  if process.returncode != 0:
    print("Error during ffmpeg execution:")
    print(process.stderr)
    raise RuntimeError("ffmpeg command failed")

  return temp_output_filename

def audio_to_filename(fname, basename=basename):
    """Translate the reply_filename from the database into an actual file 
    path on disk."""

    return os.path.join(basename, "uploads", fname + ".wav")
   

#################### Audio Prompting and Timing Adjustment ####################

def assemble_words(asr_result: dict):
  nested_list = [[w['word'] for w in s['words']] for s in asr_result['segments']]
  return [item for sublist in nested_list for item in sublist]

def filter_words(words: List[dict], prompt_time: float):
  results = []
  for word in words:
    if word['start'] < prompt_time:
      continue
    word['start'] -= prompt_time
    word['end'] -= prompt_time
    results.append(word)
  return results

def filter_segment(segment: dict, prompt_time: float):
  if segment['end'] < prompt_time:
    return None
  else:
    segment['start'] -= prompt_time
    segment['end'] -= prompt_time
    segment['words'] = filter_words(segment['words'], prompt_time)
    return segment

def adjust_timing(asr_result: Dict[str, Any], 
                  prompt_length: float=1, # Seconds
                  ) -> Dict[str, Any]:
  """Filter out ASR results that occur during the audio prompt, and adjust 
  timestamps to be relative to the end of the prompt."""
  filtered = copy.deepcopy(asr_result)
  new_segments = []
  for segment in filtered['segments']:
    new_segment = filter_segment(segment, prompt_length)
    if new_segment is not None:
      new_segments.append(new_segment)
  filtered['segments'] = new_segments
  filtered['text'] = assemble_words(filtered)
  filtered['note'] = 'Used English prompt'
  return filtered


def get_highest_snr_files_with_duration(db_file: str, 
                                        project_name: str = 'quick',
                                        ) -> Dict[str, Tuple[str, float]]:
    """
    For each user in the database, retrieves the reply_filename of their trial 
    with the highest SNR for a given project,
    
    Returns:
        dict: { 'username': ('/full/path/to/file.wav', duration_in_seconds) }
    """
    query = """
        SELECT u.username, r.reply_filename
        FROM users u
        JOIN audio_results r ON u.id = r.subject
        JOIN audio_trials t ON r.trial = t.id
        WHERE t.project = ?
        GROUP BY u.username
        HAVING t.snr = MAX(t.snr);
    """
    
    results_dict = {}
    
    with sqlite3.connect(db_file) as con:
        cur = con.cursor()
        # Fetch the username and filename for the highest SNR trial per user
        results = cur.execute(query, (project_name,)).fetchall()
        
        for username, filename in results:
            if filename:
                # 1. Convert to full pathname
                full_path = audio_to_filename(filename)
                
                # 2. Calculate the length in seconds
                duration = get_wav_duration_seconds(full_path)
                
                # 3. Save as a tuple in the dictionary
                results_dict[username] = (full_path, duration)
            else:
                # Handle edge cases where a trial might not have a reply_filename yet
                results_dict[username] = (None, -1.0)
                
    return results_dict


#################### ASR Worker Functions ####################

# --- Global variable to hold the worker's specific model ---
worker_asr_engine = None

def init_worker(asr_class_name: str, model_name: str):
    """
    Initializes the PyTorch model INSIDE the worker process.
    This prevents PyTorch from trying to share file descriptors across processes.
    """
    global worker_asr_engine
    
    # Instantiate the model
    asr_class = getattr(asr, asr_class_name)
    worker_asr_engine = asr_class(model_name)

def get_audio_queue(con: sqlite3.Connection):
    cur = con.execute(
      "SELECT audio_results.id, reply_filename, project, data, users.username "
      "FROM audio_results "
      "LEFT JOIN audio_trials ON audio_results.trial = audio_trials.id "
      "LEFT JOIN audio_asr ON audio_results.id = audio_asr.ref "
      "LEFT JOIN users ON audio_results.subject = users.id "
      "WHERE audio_asr.ref IS NULL "    # This catches rows that DON'T EXIST in audio_asr
      "   OR audio_asr.data IS NULL "   # This catches rows that exist but are NULL
      "   OR audio_asr.data = ''")      # This catches rows that exist but are empty
    q = cur.fetchall()
    cur.close()
    print(f'Need to perform ASR on {len(q)} trials.')
    print('Samples rows are:', q[:20])
    return q


def update(con: sqlite3.Connection, rowid: int, res: dict):
    res_json = json.dumps(res)
    cur = con.cursor()
    
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_audio_asr_ref ON audio_asr (ref)")
    
    sql = "INSERT OR REPLACE INTO audio_asr (ref, data) VALUES (?, ?)"
    
    try:
        cur.execute(sql, (rowid, res_json))
        con.commit()
    finally:
        cur.close()


def recognize_with_prompt(audio_path: str, 
                          prompt_path: str,
                          prompt_length: float,
                          adjust_timing: bool = True) -> Dict[str, Any]:
    """Concatenates the prompt audio with the target audio, runs ASR on the 
    combined file, and then filters the results to only include words that 
    occur after the prompt."""
    combined_path = concatenate_audio_files(prompt_path, audio_path)
    combined_result = {}
    try:
        asr_result = worker_asr_engine.recognize(combined_path)
        if adjust_timing:
          adjusted_result = adjust_timing(
            asr_result, prompt_length=prompt_length)
        else:
          adjusted_result = asr_result
    finally:
        os.remove(combined_path)
    return adjusted_result


def process_audio_task(task: Tuple, 
                       project_list: List[str], 
                       audio_prompt_dict: Dict[str, Tuple[str, float]] = {},
                       ) -> Tuple[int, Optional[Dict[str, Any]], Optional[str]]:
    """
    Executes the expensive ASR task using the process-local model.
    """
    global worker_asr_engine
    
    # SQL Result: audio_results.id, reply_filename, project, data, users.username
    rowid, fname, project, audio_asr_data, username = task
    test_filename = audio_to_filename(fname)
    try:
        if project in project_list and username in audio_prompt_dict:
          prompt_filename, prompt_audio_length = audio_prompt_dict[username]
          print('\n**********************************************')
          print('Adding prompt for user', username, 'in project', project, 
                'of length', prompt_audio_length, 'seconds')
          asr_result = recognize_with_prompt(test_filename, 
                                             prompt_filename, 
                                             prompt_audio_length, 
                                             adjust_timing=False)
          asr_result2 = worker_asr_engine.recognize(test_filename)
          print('ASR result with prompt:', asr_result['text'])
          print('')
          print('ASR result without prompt:', asr_result2['text'])
          sys.stdout.flush()
        else:
          asr_result = worker_asr_engine.recognize(test_filename)
        
        return rowid, asr_result, None
    except Exception as e:
        return rowid, None, str(e)

#################### MAIN Program ####################

def main(asr_class_name: str, 
         model_name: str,
         db_file: str, 
         single_word_projects: str = '',
         num_workers: int = 1,
         audio_prompt_dict: Dict[str, Tuple[str, float]] = {}
         ):
    
    print(f'Offline_ASR started at {datetime.now()} with {db_file}')
    single_word_project_list = single_word_projects.split(',') if single_word_projects else []
    
    # Fetch all pending tasks in the main process
    with sqlite3.connect(db_file) as con:
        tasks = get_audio_queue(con)

    if not tasks:
        print("No tasks found.")
        return

    print(f"Processing {len(tasks)} tasks using {num_workers} worker(s)...")

    # Bind the static arguments to our worker function
    worker_func = partial(
        process_audio_task,
        project_list=single_word_project_list,
        audio_prompt_dict=audio_prompt_dict
    )

    row_count = 0

    # Re-open the DB connection in the main thread for writing results
    with sqlite3.connect(db_file) as con:
        if num_workers <= 1:
            # For a single worker, manually initialize the global engine in the main thread
            init_worker(asr_class_name, model_name)
            for task in tqdm(tasks):
                rowid, asr_result, error = worker_func(task)
                if error:
                    print(f"\n[!] Error on row {rowid}: {error}")
                    continue
                if asr_result:
                    update(con, rowid, asr_result)
                    row_count += 1
                sys.stdout.flush()  # Ensure progress bar updates correctly
        else:
            # For multiprocessing, tell the pool to run init_worker on boot
            with Pool(
                processes=num_workers, 
                initializer=init_worker, 
                initargs=(asr_class_name, model_name)
            ) as pool:
                for rowid, asr_result, error in tqdm(pool.imap_unordered(worker_func, tasks), total=len(tasks)):
                    if error:
                        print(f"\n[!] Error on row {rowid}: {error}")
                        continue
                    if asr_result:
                        update(con, rowid, asr_result)
                        row_count += 1
                    sys.stdout.flush()  # Ensure progress bar updates correctly

    print(f'Finished processing {row_count} rows.')

    
def deduplicate(db_file: str, **kw):
  """????"""
  con = sqlite3.connect(db_file)
  dup, sep = "json_extract(data, '$.' || ?) = ?", " AND "
  clause = sep.join((dup,) * len(kw))
  args = sum(kw.items(), ())
  cur = con.cursor()
  cur.execute("DELETE FROM audio_asr WHERE " + clause, args)
  con.commit()
  con.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    models = [
            "tiny.en", "tiny",
            "base.en", "base",
            "small.en", "small",
            "medium.en", "medium",
            "large"]
    parser.add_argument("--model", default="medium.en", choices=models, help=(
            "which whisper model size to use (default: large); see: "
            "https://github.com/openai/whisper#available-models-and-languages"))
    parser.add_argument("--dbfile", 
                        default=os.path.join(basename, "experiments_malcolm.db"), 
                        help="Which SQLite3 database file to process")
    parser.add_argument("--single_word_projects", 
                        default="cnc,win,nu6",
                        help="Which projects need language prompt")
    parser.add_argument("--language_prompt_file", 
                        default="EnglishPrompt.wav",
                        help="Audio file to prompt recognizer to use English")
    parser.add_argument(
            "--prompted", dest="asr", default="WhisperASR",
            action="store_const", const="PromptedWhisperASR", help=(
                "use the correct answer as the model prompt; can help accuracy "
                "but can also bias results towards correct"))
    parser.add_argument("--force", action="store_true")
    
    parser.add_argument("--num_workers", type=int, default=1,
                        help="Number of concurrent workers for ASR processing. "
                             "Warning: Running multiple workers will multiply your RAM/VRAM usage.")
    
    args = parser.parse_args()

    assert os.path.exists(args.dbfile)
    assert os.path.exists(args.language_prompt_file), f'Missing {args.language_prompt_file}'

    if args.force:
        model_type = "default" if args.asr == "WhisperASR" else "prompted"
        deduplicate(args.dbfile, model_name=args.model, model_type=model_type)
    
    if False:
      filename = get_highest_snr_quicksin_reply(args.dbfile, 'A3S03', 'quick')
      print(filename)
      sys.exit(0)

    # Get the a dictionary of good audio responses that we can prepend to the 
    # target audio for single-word tests.
    audio_prompt_dict = get_highest_snr_files_with_duration(args.dbfile,
                                                            'quick')
    count = 0
    for username, (prompt_filename, prompt_length) in audio_prompt_dict.items():
        if prompt_filename is not None:
            print(f"User '{username}' has a prompt file '{prompt_filename}' of length {prompt_length:.2f} seconds.")
            count += 1
        else:
            print(f"User '{username}' does not have a valid prompt file.")
    print(f"Total users with valid prompt files: {count}")

    # Notice we pass the string names here now
    main(args.asr, 
         args.model, 
         args.dbfile,
         args.single_word_projects, 
         args.num_workers,
         audio_prompt_dict)
