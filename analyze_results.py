from absl import app, flags
import csv
from dataclasses import dataclass
import json
import matplotlib.pyplot as plt
import numpy as np
from numpy.typing import ArrayLike, NDArray
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import sqlite3


def get_all_sql_data(database: str = 'experiments.db'):
  """Get all the test results from the database, joining all the tables."""
  con = sqlite3.connect(database)
  print(type(con))
  cur = con.cursor()
  query = """SELECT * FROM audio_results
    LEFT JOIN audio_trials ON audio_results.trial=audio_trials.id
    LEFT JOIN users ON subject=users.id
    LEFT JOIN (select * from user_info where info_key='test-type' group by user)
                as 'user_info' ON users.id=user_info.user
    LEFT JOIN audio_asr ON audio_results.id=audio_asr.ref
    LEFT JOIN audio_annotations ON audio_results.id=audio_annotations.ref
    where info_key='test-type'
    """
  all_query_results = cur.execute(query).fetchall()
  return all_query_results


def get_all_test_transcripts(database: str = 'experiments.db'):
  """Get all the test transcripts from the database.
  
  Returns:   
    id, project, snr, lang, level_number, trial_number, filename, answer, active
  """
  con = sqlite3.connect(database)
  # print(type(con))
  cur = con.cursor()
  query = """SELECT * FROM audio_trials
          """
  all_query_results = cur.execute(query).fetchall()
  return all_query_results


def fix_random_user_names(text_tag: str) -> str:
  match text_tag:
    case 'DFe3RNee' | 'NQE7QNNm':
      return 'A0S1' # Emily'
    case 'mMD4mHfH':
      return 'A0S2' # 'Varsha'
    case 'QA7D33Nr':
      return 'A0S3' # 'Shreyas'
  return text_tag

################### Global Homonyms ################################

def read_homonyms(filename: str = 'homonym_list.csv', 
                  starting_dict={}) -> Dict[str, set]:
  """Read a list of homonyms from a CSV file. 
  
  Start with an initial homonym list and rationalize it first by making sure
  all words are bidirectionally included.
  
  Then read the rest from a CSV file, removing the null entries
  """
  # Rationalize the initial list by making sure all homonyms are listed
  homonym_list = {}
  for key, words in starting_dict.items():
    words_set = set(words) | set([key,])
    for word in words_set:
      homonym_list[word] = words_set - set([word])

  # print(homonym_list)
  with open(filename, 'r') as f:
    for line in f:
      if line.startswith('#'):
        continue
      line = line.split('#', 1)[0].rstrip()  # Remove comments on each line
      line = line.strip()
      if not line: 
        continue
      words = line.split(',')
      words = [w.strip() for w in words]
      words = [w for w in words if w]
      if len(words) < 2:
        print('Did not find enough words:', line)
      for word in words:
        if word not in homonym_list:
          homonym_list[word] = set(words) - set([word])
        else:
          homonym_list[word] = set(words) or (set(homonym_list[word]) - set(word))
  return homonym_list


def format_homonyms(current_word, 
                    homonym_dict: Dict[str, set[str]],
                    keep_hyphens: bool = False) -> set[str]:
  """Given a new word and the homonym dictionary, return the full set of 
  homonyms as a set of words.

  When preparing the ground truth, we want to keep any hyphenated words so we
  can process them correctly later.
  """
  current_words = set(current_word.split('/'))
  all_words = set()
  for word in current_words:
    word = normalize_word(word, keep_hyphens=keep_hyphens)
    all_words = all_words | set([word])
    if word in homonym_dict:
      all_words = all_words | homonym_dict[word]
  return all_words

def split_words(original_list: list[str], 
                word: str, 
                new_words: list[str]) -> list[str]:
  """Split a word in a list of words, replacing the original word with the new words."""
  result = []
  for w in original_list:
    if w == word:
      print(f'Splitting {word} into {new_words}')
      result.extend(new_words)
    else:
      result.append(w)
  return result

def process_all_ground_truth(db_file: str,
                             homonym_list: Dict[str, set[str]]) -> Dict[Tuple[str, int, int], list[set]]:
  # Create a list of ground truths, indexed. by the test name, list number, and 
  # then sentence number.
  # https://github.com/MalcolmSlaney/SpeechInNoise/blob/81c92d3e8a7e7db6d5f62f511d4bebe8ef7f883c/schema.sql#L57
  test_transcripts = get_all_test_transcripts(db_file)
  print(f'Read ground truth for {len(test_transcripts)} tests.')

  all_ground_truth = {}
  for t in test_transcripts:
    test_name = t[1]
    list_number = t[5]
    sentence_number = t[4]
    word_list = t[7].lower().split(' ') # a list of words (some with / to separate homonyms)
    ground_truth = [format_homonyms(word, homonym_list, keep_hyphens=True) 
                    for word in word_list]
    all_ground_truth[(test_name, list_number, sentence_number)] = ground_truth
  return all_ground_truth


################### Result Class ################################

@dataclass
class QS_result:
  """This dataclass contains everything that we retrieve from the web database
  to describe one QuickSIN sentence trial.  It contains information about the s
  ubject, the trial (list and sentence number), and the ASR results (as computed
  on the server). We extend it to say if the audioloigist and the ASR systems
  match.

  Note: These fields must be in the same order as the SQL query above.
  """
  results_id: int
  results_subject: int
  results_trial: int
  results_reply_filename: str
  # results_reply_asr: str
  results_time: str              # quick_results
  trials_id: int
  trials_project: str            # Type of test (qs, azbio, etc)
  trials_snr: int
  trials_lang: str
  trials_level_number: int # The qs sentence number (1 based)
  trials_trial_number: int # The qs list number (1 based)
  trials_filename: str # Which sound file was played
  trials_answer: str # Comma separated list of true words
  trials_active: bool  # ???
  user_id: int
  user_name: str # Audiologist#Subject#
  user_ip: str
  user_time: str # users
  user_info_id: int
  user_info_key: str # What kind of info: searchParams or test-type?
  user_info_value: str
  user_info_time: str
  asr_id: int
  # asr_ref: int
  asr_results: Union[str, Dict[str, Any]]  # json encoded asr results
  annotation_ref: int
  annotation_matches: Union[str, List[bool]] # quick_annotations (human labels)
  asr_words: Optional[List[str]] = None  # List of all words recognized by ASR
  asr_matches: Optional[List[bool]] = None # Whether ASR found the keyword
  asr_times: Optional[List[float]] = None # The starting time for each matched word
  audiology_asr_matches: Optional[List[bool]] = None


def normalize_word(word:str, keep_hyphens:bool = False) -> str:
  """Remove all but the letters in a word."""
  if keep_hyphens:
    return re.sub(r'[^\w-]', '', word.lower())
  return re.sub(r'[^\w]', '', word.lower())

def normalize_results(a_result: QS_result) -> QS_result:
  """Normalize one result object.  This involves the following steps:
  1) Convert user names that look random into fixed user names
  2) Convert the ASR result from a setence to a list of words
  3) Convert the annotation matches (audiologist judgements) from JSON to a list of booleans
  4) # Convert the ground truth from CSV to a list of words
     # no longer needed since we collect the ground truth at scoring time
  5) Finally, convert the human recognition results into a list of recognized words.

  Return the original result object after these enhancements.
  """
  a_result.user_name = fix_random_user_names(a_result.user_name)
  if isinstance(a_result.asr_results, str) and a_result.asr_results:
    a_result.asr_results = json.loads(a_result.asr_results)

  if isinstance(a_result.annotation_matches, str):
    a_result.annotation_matches = json.loads(a_result.annotation_matches)

  if isinstance(a_result.trials_answer, str):
    a_result.trials_answer = a_result.trials_answer.split(' ')

  # Split recognition into a list of words
  a_result.asr_words = []
  if (a_result.asr_results and 'segments' in a_result.asr_results and
      a_result.asr_results['segments'] and
      'words' in a_result.asr_results['segments'][0]):
    # Remove punctation and spaces to normalize ASR results
    asr_words = [w['word'] for w in a_result.asr_results['segments'][0]['words']]
    a_result.asr_words = asr_words
  return a_result


def asr_match(desired_word_set: Union[set[str], str], 
             recognized_words: dict) -> Tuple[bool, float]:
  """Determine if we can find a keyword in the recognized words.
  Slightly more complicated in cases of hyphenated words.
  
  Recognized_word is a dictionary with 'word', 'start', 'end', 'prob' fields.
  
  Returns:
    is_match:bool, 
    start_time:float
  """
  if isinstance(desired_word_set, set):
    # Did the ASR recognize any of the words in the homonym set?
    results = [asr_match(w, recognized_words) for w in desired_word_set]
    return any(r[0] for r in results), results[0][1]  # Return first recognized word
  elif isinstance(desired_word_set, str):
    desired_word:str = desired_word_set
    if '-' in desired_word[1:]:  # Ignore leading hyphen
      parts = desired_word.split('-')
      parts[1] = set([parts[1], '-' + parts[1]])
      results = [asr_match(w, recognized_words) for w in parts]
      has_all_parts = all(r[0] for r in results)
      return has_all_parts, results[0][0]  # Return first recognized time
    for reco in recognized_words:
        asr_word = normalize_word(reco['word'])
        desired_word = normalize_word(desired_word)
        if asr_word == desired_word:
          return True, reco['start']
    return False, np.nan
  raise ValueError(f'Unknown type for desired_word_set: {type(desired_word_set)}')


def score_asr_system(a_result: QS_result,
                     all_ground_truth: Dict[Tuple[str, int, int], 
                                            list[set[str]]],
                     debug: bool = False):
  # Score the ASR results, creating a list of true/false
  # ground truth is a list of sets of words, one set per keyword
  ground_truth = all_ground_truth[(a_result.trials_project,
                                   a_result.trials_trial_number,
                                   a_result.trials_level_number)]
  word_matches = []
  match_times = []
  # Parse the JSON result, if we haven't already done that.
  if isinstance(a_result.asr_results, str):
    a_result.asr_results = json.loads(a_result.asr_results)
  if isinstance(a_result.annotation_matches, str):
    a_result.annotation_matches = json.loads(a_result.annotation_matches)
  # Check if segments exist and contain words
  if (a_result.asr_results and 'segments' in a_result.asr_results and
      a_result.asr_results['segments'] and
      'words' in a_result.asr_results['segments'][0]):
    for word_truth_set in ground_truth:
      # For each word in the ground truth, see if ASR found it
      is_match, word_time = asr_match(word_truth_set,
                                      a_result.asr_results['segments'][0]['words'])
      word_matches.append(is_match)
      match_times.append(word_time)
  else:
    # Handle cases where segments or words are missing
    # For example, you could set all matches to False and times to NaN
    word_matches = [False] * len(ground_truth)
    match_times = [np.nan] * len(ground_truth)
  if debug:
    print(f'Want these words: {ground_truth}')
    print(f'   in ASR results: {a_result.asr_words}')
    print(f'   results: {word_matches} at {match_times}s')
  a_result.asr_matches = word_matches
  a_result.asr_times = match_times


def score_matches(a_result: QS_result, debug: bool = False):
  """Compare the audilogy and ASR annotations.
  """
  matches = [not(a ^ b) for a,b in zip(a_result.asr_matches, a_result.annotation_matches)]
  if debug:
    print(a_result.asr_matches, a_result.annotation_matches, matches)
  a_result.audiology_asr_matches = matches



def convert_sql_to_results(all_query_results,
                           all_ground_truth: List[set[str]]) -> List[QS_result]:
  """Convert the SQL database into a list of qs_result objects.
  """
  debug_test_count = {}
  all_results = []
  no_asr_results = 0
  for db_result in all_query_results: # Iterate through SQL responses
    a_result = QS_result(*db_result)
    if a_result.asr_results is None:
      no_asr_results += 1
      continue
    # if a_result.trials_project != 'quick':
    #   not_quick_tests += 1
    # else:
    if True:
      test_name = a_result.trials_project
      if test_name not in debug_test_count:
        debug_test_count[test_name] = 0
      debug_test_count[test_name] += 1
      # print(test_name, debug_test_count[test_name])

      normalize_results(a_result)
      # if not a_result.user_name.startswith('A'):
      #   continue
      if a_result.user_name in ['A1P8', 'A1P9', 'A2P15']:
        print(f'Skipping user {a_result.user_name} for not following directons')
        continue
      # if a_result.user_info_value != 'pilot':
      #   continue
      score_asr_system(a_result, all_ground_truth, 
                       debug_test_count[test_name] < 3)
      score_matches(a_result, debug_test_count[test_name] < 3)
    all_results.append(a_result)
  return all_results


def save_results_as_csv(all_results: List[QS_result],
                        csv_file: str = 'quicksin_results.csv') -> str:

  # Define the header row based on the QS_result dataclass fields you want to include
  header = [
      'results_id', 'results_subject', 'results_trial', 'results_reply_filename',
      'results_time', 'trials_id', 'trials_project', 'trials_snr', 'trials_lang',
      'trials_level_number', 'trials_trial_number', 'trials_filename',
      'trials_answer', 'trials_active', 'user_id', 'user_name', 'user_ip',
      'user_time', 'user_info_id', 'user_info_key', 'user_info_value',
      'user_info_time', 'asr_id', 'asr_results', 'annotation_ref',
      'annotation_matches', 'asr_words', 'asr_matches', 'asr_times',
      'audiology_asr_matches'
  ]

  # Write the data to the CSV file
  with open(csv_file, 'w', newline='') as f:
      writer = csv.writer(f)
      writer.writerow(header)  # Write the header row
      for result in all_results:
          row_data = [
              result.results_id, result.results_subject, result.results_trial,
              result.results_reply_filename, result.results_time,
              result.trials_id, result.trials_project, result.trials_snr,
              result.trials_lang, result.trials_level_number,
              result.trials_trial_number, result.trials_filename,
              # Join list fields into strings for CSV compatibility
              ','.join(result.trials_answer) if isinstance(result.trials_answer, list) else result.trials_answer,
              result.trials_active, result.user_id, result.user_name, result.user_ip,
              result.user_time, result.user_info_id, result.user_info_key,
              result.user_info_value, result.user_info_time, result.asr_id,
              json.dumps(result.asr_results), # Convert dict to JSON string
              json.dumps(result.annotation_matches), # Convert list to JSON string
              ','.join(result.asr_words) if isinstance(result.asr_words, list) else result.asr_words,
              ','.join([str(m) for m in result.asr_matches]) if isinstance(result.asr_matches, list) else result.asr_matches,
              ','.join([str(t) for t in result.asr_times]) if isinstance(result.asr_times, list) else result.asr_times,
              ','.join([str(m) for m in result.audiology_asr_matches]) if isinstance(result.audiology_asr_matches, list) else result.audiology_asr_matches
          ]
          writer.writerow(row_data)

  print(f'Results written to {csv_file}')
  return csv_file

######################## Confusion Matrices #########################


def accumulate_errors(sum: NDArray, human: ArrayLike, asr: ArrayLike) -> None:
  assert sum.ndim == 2
  assert sum.shape == (2, 2)
  for h, a in zip(human, asr):
    sum[int(h), int(a)] += 1

# sum = np.zeros((2, 2), dtype=int)
# accumulate_errors(sum, [True, False], [True, True])
# sum


def all_test_confusions(all_results: List[QS_result]) -> Dict[str, NDArray]:
  """Create a dictionary of confusion matrices, one per test type.
  Each confusion matrix is indexed by
    human, asr
  """
  valid_subject_re = re.compile(r'A\d+[SP]\d+')
  all_confusions = {}
  for r in all_results:
    if valid_subject_re.match(r.user_name):
      test_name = r.trials_project
      if test_name not in all_confusions:
        all_confusions[test_name] = np.zeros((2, 2), dtype=int)
      accumulate_errors(all_confusions[test_name],
                        r.annotation_matches, r.asr_matches)
  return all_confusions

# all_confusions = all_test_confusions(all_results)
# all_confusions


def plot_confusions(all_confusions: Dict[str, NDArray]):
  """For each test type, plot a confusion matrix noting whether the 
  ASR or the human scorer heard the same keywords.
  """
  centers = [0, 1]
  for i, test_name in enumerate(all_confusions.keys()):
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

######################## Generate HTML Summary Page #########################

def generate_html_report(all_results: List[QS_result],
                         all_ground_truth: Dict[Tuple[str, int, int], str],
                         only_discrepancies: bool = True,
                         filter_tests: List[str] = None,
                         max_number: int = 10000000000) -> Tuple[str, int]:
  # Generate an HTML report of the results, perhaps only the discrepancies.
  html_output = """
  <!DOCTYPE html>
  <html>
  <head>
  <title>Online SPIN Test vs Audiologist Discrepancies</title>
  <style>
    table {
      border-collapse: collapse;
      width: 100%;
    }
    th, td {
      border: 1px solid #dddddd;
      text-align: left;
      padding: 8px;
    }
    th {
      background-color: #f2f2f2;
    }
    .discrepancy {
      background-color: #ffcccc;
    }
  </style>
  </head>
  <body>

  <h1>QuickSIN ASR vs Audiologist Discrepancies</h1>

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

  valid_subject_re = re.compile(r'A\d+[PS]\d+')
  row_count = 0
  for result in all_results:
    if not valid_subject_re.match(result.user_name):
      continue
    if filter_tests and result.trials_project not in filter_tests:
      continue
    # Check if there's any disagreement between audiology vs. asr_matches
    if only_discrepancies and result.annotation_matches == result.asr_matches:
      continue
    html_output += "<tr>"
    html_output += f"<td>{result.user_name} {valid_subject_re.match(result.user_name)}</td>"
    html_output += f"<td>{result.trials_project}</td>"
    html_output += f"<td>{result.trials_trial_number}</td>"
    html_output += f"<td>{result.trials_level_number}</td>"
    # Display ground truth from all_ground_truth dictionary
    ground_truth = all_ground_truth.get((result.trials_project, 
                                         result.trials_trial_number, 
                                         result.trials_level_number), ["N/A"])
    ground_truth_string = ', '.join(['/'.join(homonym_list) for homonym_list in ground_truth])
    html_output += f"<td>{ground_truth_string}</td>"
    html_output += f"<td>{', '.join(result.asr_words) if result.asr_words else 'N/A'}</td>"
    html_output += f"<td>{result.annotation_matches}</td>"
    html_output += f"<td>{result.asr_matches}</td>"
    # https://www.w3schools.com/charsets/ref_utf_dingbats.asp
    if all(result.audiology_asr_matches):
      html_output += "<td>&#9989;</td>" # a check mark
    else:
      html_output += "<td>&#10008;</td>" # heavy ballot x
    # html_output += f"<td>{result.audiology_asr_matches}</td>"
    audio_url = f"https://quicksin.stanford.edu/uploads/{result.results_reply_filename}.wav"
    html_output += f'<td><audio controls> <source src={audio_url} type=audio/mp4>Your browser does not support the audio element.</audio></td>'
    html_output += "</tr>\n"
    row_count += 1
    if row_count >= max_number:
      break

  html_output += """
  </table>

  </body>
  </html>
  """
  return html_output, row_count

FLAGS = flags.FLAGS

# Define flags
flags.DEFINE_string('dbfile', 'experiemnts.db', 
                    'Sqllite3 database to read the experients results.')
flags.DEFINE_string('homonyms', 'homonym_list.csv', 
                    'CSV file containing list of homonyms.')
# flags.DEFINE_boolean('debug', False, 'Enable debug mode.')

def main(argv):
  """Main entry point."""
  assert os.path.exists(FLAGS.dbfile), f'Database file {FLAGS.dbfile} does not exist.'
  # Prepare the homonym list and then the ground truth.
  homonym_list = read_homonyms(FLAGS.homonyms, 
                               # qsb.make_homonyms_dictionary(qsb.homonyms)
                               )
  all_ground_truth = process_all_ground_truth(FLAGS.dbfile, homonym_list)

  # Read and normalize the user and asr results from the database.
  all_query_results = get_all_sql_data(FLAGS.dbfile)
  all_results = convert_sql_to_results(all_query_results,
                                       all_ground_truth)
  csv_file = save_results_as_csv(all_results, 'quicksin_results.csv')

  # Summarize the test results
  all_confusions = all_test_confusions(all_results)
  plot_confusions(all_confusions)
  plt.savefig('confusion_matrices.png')

  html_report, row_count = generate_html_report(
      all_results, all_ground_truth,
      only_discrepancies=True,
      filter_tests=[],
      max_number=1000)

  with open('asr_audiology_discrepancies.html', 'w') as f:
    f.write(html_report)
  print(f'Wrote {row_count} discrepancy rows to asr_audiology_discrepancies.html')

  total_tests = 0
  total_correct = 0
  print('Test accuracies:')
  for test, results in all_confusions.items():
    num_tests = np.sum(results)
    num_correct = results[0,0] + results[1,1]
    total_tests += num_tests
    total_correct += num_correct
    print(f'{test}: {num_correct/num_tests*100}%')
  print(f'Overall: {total_correct/total_tests*100}%')

if __name__ == "__main__":
    app.run(main)
