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
from typing import List
from multiprocessing import Pool
from functools import partial

import asr

default_sample_rate = 22050
basename = pathlib.Path(__file__).parents[0]

# --- Global variable to hold the worker's specific model ---
worker_asr_engine = None

def init_worker(asr_class_name: str, model_name: str):
    """
    Initializes the PyTorch model INSIDE the worker process.
    This prevents PyTorch from trying to share file descriptors across processes.
    """
    global worker_asr_engine
    import asr
    
    # Instantiate the model
    asr_class = getattr(asr, asr_class_name)
    worker_asr_engine = asr_class(model_name)

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

def adjust_timing(asr_result, prompt_time: float=1):
  filtered = copy.deepcopy(asr_result)
  new_segments = []
  for segment in filtered['segments']:
    new_segment = filter_segment(segment, prompt_time)
    if new_segment is not None:
      new_segments.append(new_segment)
  filtered['segments'] = new_segments
  filtered['text'] = assemble_words(filtered)
  filtered['note'] = 'Used English prompt'
  return filtered


def audio_queue(con: sqlite3.Connection):
    cur = con.execute(
            "SELECT audio_results.id, reply_filename, project, data "
            "FROM audio_results "
            "LEFT JOIN audio_trials ON audio_results.trial = audio_trials.id "
            "LEFT JOIN audio_asr ON audio_results.id=audio_asr.ref "
            "WHERE audio_asr.data IS NULL OR audio_asr.data = ''")
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


def process_audio_task(task, project_list, eng_prompt):
    """
    Executes the expensive ASR task using the process-local model.
    """
    global worker_asr_engine
    
    rowid, fname, project, data = task
    filename = os.path.join(basename, "uploads", fname)
    
    try:
        if project in project_list:
            asr_result = worker_asr_engine.recognize(
                filename, 
                initial_prompt=eng_prompt
            )
        else:
            asr_result = worker_asr_engine.recognize(filename)
        
        return rowid, asr_result, None
    except Exception as e:
        return rowid, None, str(e)


def main(asr_class_name: str, 
         model_name: str,
         db_file: str, 
         single_word_projects: str = '',
         num_workers: int = 1):
    
    print(f'Offline_ASR started at {datetime.now()} with {db_file}')
    single_word_project_list = single_word_projects.split(',') if single_word_projects else []
    
    eng_prompt = "The following are short, clearly spoken English words."

    # Fetch all pending tasks in the main process
    with sqlite3.connect(db_file) as con:
        tasks = audio_queue(con)

    if not tasks:
        print("No tasks found.")
        return

    print(f"Processing {len(tasks)} tasks using {num_workers} worker(s)...")

    # Bind the static arguments to our worker function
    worker_func = partial(
        process_audio_task,
        project_list=single_word_project_list,
        eng_prompt=eng_prompt
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
                sys.stddout.flush()  # Ensure progress bar updates correctly
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
                    sys.stddout.flush()  # Ensure progress bar updates correctly

    print(f'Finished processing {row_count} rows.')

    
def deduplicate(db_file: str, **kw):
    con = sqlite3.connect(db_file)
    dup, sep = "json_extract(data, '$.' || ?) = ?", " AND "
    clause = sep.join((dup,) * len(kw))
    args = sum(kw.items(), ())
    cur = con.cursor()
    cur.execute("DELETE FROM audio_asr WHERE " + clause, args)
    con.commit()
    cur.close()

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
    
    # Notice we pass the string names here now
    main(args.asr, 
         args.model, 
         args.dbfile,
         args.single_word_projects, 
         args.num_workers)
