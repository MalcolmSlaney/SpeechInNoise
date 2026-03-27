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

import asr

default_sample_rate = 22050
basename = pathlib.Path(__file__).parents[0]

def get_wav_duration_seconds(file_path: str) -> float:
  """
  Reads a WAV file and returns its length in seconds.

  Args:
    file_path: Path to the WAV audio file.

  Returns:
    The duration of the audio file in seconds as a float.
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

  Args:
    input_file1: Path to the first input audio file.
    input_file2: Path to the second input audio file.

  Returns:
    The filename of the temporary concatenated audio file.
  """
  temp_output_filename = tempfile.mktemp(suffix='.wav')

  # ffmpeg -i audio1.wav -i audio2.wav -filter_complex "[0:a]aresample=resampler=shorter:osr=[TARGET_SAMPLE_RATE][a0];[1:a]aresample=resampler=shorter:osr=[TARGET_SAMPLE_RATE][a1];[a0][a1]concat=n=2:v=0:a=1[out]" -map "[out]" -c:a aac output.m4a


  cmd = ('ffmpeg -i {} -i {} -filter_complex '
         '"[0:a]aresample={}[a0];[1:a]aresample={}[a1];'
         '[a0][a1]concat=n=2:v=0:a=1[out]" -map "[out]" {}')
  formatted_cmd = cmd.format(input_file1, input_file2, 22050, 22050, temp_output_filename)

  # print(f"Running command: {formatted_cmd}")
  process = subprocess.run(formatted_cmd, shell=True, capture_output=True, text=True)

  if process.returncode != 0:
    print("Error during ffmpeg execution:")
    print(process.stderr)
    raise RuntimeError("ffmpeg command failed")
  # else:
  #   print("ffmpeg output:")
  #   print(process.stdout)

  return temp_output_filename


def assemble_words(asr_result: dict):
  nested_list = [[w['word'] for w in s['words']] for s in asr_result['segments']]
  return [item for sublist in nested_list for item in sublist]

def filter_words(words: List[dict], prompt_time: float):
  results = []
  for word in words:
    # print(f'Checking {word["word"]} ending at {word["end"]}')
    if word['start'] < prompt_time:
      continue
    word['start'] -= prompt_time
    word['end'] -= prompt_time
    results.append(word)
  return results

def filter_segment(segment: dict, prompt_time: float):
  # print(f'Checking segment ending at {segment["end"]}')
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
            "SELECT audio_results.id, reply_filename, project "
            "FROM audio_results "
            "LEFT JOIN audio_trials ON audio_results.trial = audio_trials.id "
            "LEFT JOIN audio_asr ON audio_results.id=audio_asr.ref "
            "WHERE audio_asr.data IS NULL OR audio_asr.data = ''")
    q = cur.fetchall()
    cur.close()
    print(f'Need to perform ASR on {len(q)} trials.')
    return q

def update(con: sqlite3.Connection, rowid: int, res: str):
    res = json.dumps(res)
    cur = con.cursor()
    cur.execute("INSERT INTO audio_asr (ref, data) VALUES (?, ?)", (rowid, res))
    con.commit()
    cur.close()


def main(asr_engine: asr.WhisperASREngine,
         db_file: str, 
         single_word_projects: str = '',
         prompt_file: str = ''):
    print('Offline_ASR started at', datetime.now())
    prompt_length = get_wav_duration_seconds(prompt_file)
    single_word_project_list = single_word_projects.split(',')
    if single_word_project_list:
       print('Looking for single words in these test:', 
             single_word_project_list)
       print(f' After {prompt_length}s.')
    con = sqlite3.connect(db_file)
    row_count = 0
    for rowid, fname, project in tqdm(audio_queue(con)):
        try:
            filename = os.path.join(basename, "uploads", fname)
            print('Checking:', project, project in single_word_project_list)
            if project in single_word_project_list:
                print(rowid, filename, project, 'Add English prompt')
                new_filename = concatenate_audio_files(prompt_file, filename)
                asr_result = asr_engine.recognize(new_filename)
                asr_result = adjust_timing(asr_result, prompt_length)
                # pprint.pprint(asr_result)
            else:
              asr_result = asr_engine.recognize(filename)
            update(con, rowid, asr_result)
            row_count += 1
        except RuntimeError as e:
            # Code to handle the exception
            print(f"An error occurred: {e}")
            print('While processing', filename)
        sys.stdout.flush()
    print(f'Finished processing {row_count} rows of speech data.')

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
    parser.add_argument("--model", default="large", choices=models, help=(
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
    # parser.add_argument(
    #         "--test", action="", help="Run a test on a single audio file"
    # )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    assert os.path.exists(args.dbfile)
    assert os.path.exists(args.language_prompt_file), f'Missing {args.language_prompt_file}'

    if args.force:
        model_type = "default" if args.asr == "WhisperASR" else "prompted"
        deduplicate(args.dbfile, model_name=args.model, model_type=model_type)
    
    
    main(getattr(asr, args.asr)(args.model), args.dbfile,
         args.single_word_projects, 
         args.language_prompt_file,
         )

