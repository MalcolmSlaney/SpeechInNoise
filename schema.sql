/*
 * Implement an online version of the QuickSIN test, to automate human
 * data collection ala this article.
 * https://pubs.aip.org/asa/jel/article/4/9/095202/3311832/Comparing-human-and-machine-speech-recognition-in
 */

CREATE TABLE version (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    hash TEXT
);

/*
 * Table that describes one user.
 */
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  ip TEXT,
  t TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

/*
 * Table for meta data about each user.  Right now it either contains entries
 * for the CGI Params (info_key is searchParams) or the type of test (info_key
 * is test-type).  Can be more than one entry per user.
 */
CREATE TABLE user_info (
  user INTEGER,
  info_key TEXT,
  value TEXT,  /* Which type of test: prepilot, pilot, patient */
  t TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(user) REFERENCES users(id)
);
CREATE TABLE pitch_trials (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  f0 INTEGER, /* base frequency */
  level_number INTEGER, /* zero indexed */
  trial_number INTEGER, /* in the current level, which trial number */
  filename TEXT, /* basename, not path */
  answer INTEGER, /* 1 for pitch goes up otherwise -1 */
  active BOOLEAN NOT NULL CHECK(active IN(0,1)) /* version control */
);
CREATE TABLE pitch_results (
  subject INTEGER,
  trial INTEGER,
  guess INTEGER,
  levels_left INTEGER, /* in case of doubled requests */
  FOREIGN KEY(subject) REFERENCES users(id),
  FOREIGN KEY(trial) REFERENCES pitch_trials(id)
);

/*
 * Table that describes all QuickSIN stimuli, lists the stimulus wave
 * file, and contains the expected keywords (comma separated, with homonyms
 * separated by /).
 */
CREATE TABLE audio_trials (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project TEXT,
  snr INTEGER,
  lang TEXT,
  level_number INTEGER, /* which sentence in this list */
  trial_number INTEGER, /* which QuickSIN list */
  filename TEXT, /* basename, not path */
  answer TEXT, /* Ground truth answer */
  active BOOLEAN NOT NULL CHECK(active IN(0,1)) /* version control */
);

CREATE UNIQUE INDEX audio_trial ON audio_trials (
    project, lang, level_number, trial_number);

/*
 * Table that describes one trial (play one sound, get one response.)
 * points to user name and trial information (above).  The ASR response
 * links to entries in this table.
 */
CREATE TABLE audio_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  subject INTEGER,
  trial INTEGER,
  reply_filename TEXT,
  t TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(subject) REFERENCES users(id),
  FOREIGN KEY(trial) REFERENCES audio_trials(id)
);

/*
 * Table that describes the ASR response for a user trial.  Contains the ASR
 * response, and is keyed to the quick_results above.
 */
CREATE TABLE audio_asr (
  ref INTEGER,
  data TEXT, /* JSON encoded dictionary of ASR Results */
  FOREIGN KEY(ref) REFERENCES audio_results(id)
);

/*
 * Table that describes which words that the audiologist identified as being
 * correctly spoken by the patient.  (We want to compare these results to the
 * ASR results in the quick_asr table.) Entries in this table are tied to the
 * quick_results table above.
 */
CREATE TABLE audio_annotations (
  ref INTEGER,
  data TEXT, /* JSON string of True/False by audiologist by keyword */
  FOREIGN KEY(ref) REFERENCES audio_results(id)
);

/* Table to track reviewer demographics and progress. */
CREATE TABLE reviewers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  t TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  role TEXT NOT NULL CHECK(role IN('student', 'audiologist')),
  years_practicing INTEGER CHECK((role = 'audiologist' AND years_practicing IS NOT NULL) OR (role = 'student' AND years_practicing IS NULL)),
  completed_tests TEXT, /* JSON array of unique patient-test pairs: [{"subject": 1, "project": "quick"}, {"subject": 2, "project": "nu6"}] */
  test_in_progress TEXT, /* Current patient-test-progress tuple: {"subject": 3, "project": "azbio", "index": 42, "total_files": 25, "files_reviewed": 10, "current_file_num": 11} or NULL if none (index is audio_results.id) */
  remaining_tests TEXT, /* JSON array of unique patient-test pairs to complete: [{"subject": 4, "project": "quick"}, {"subject": 5, "project": "nu6"}] */
  most_recent_subject INTEGER, /* The most recent subject ID that the reviewer reviewed */
  total_reviews INTEGER DEFAULT 0, /* Total number of reviews completed by this reviewer */
  played_audio TEXT, /* JSON array of audio_results.id that have been played but not yet reviewed: [42, 43, 44] */
  notes TEXT, /* Additional notes or comments about the reviewer, empty currently */
  consent_form BLOB NOT NULL /* Consent form signed by reviewer */
);

CREATE TABLE review_annotations (
  ref INTEGER,
  data TEXT,
  labeler INTEGER,
  unclear BOOLEAN DEFAULT 0 CHECK(unclear IN(0,1)), /* Marked as unclear/unsure by reviewer - files with many unclear marks may be excluded from analysis */
  FOREIGN KEY(ref) REFERENCES audio_results(id),
  FOREIGN KEY(labeler) REFERENCES users(id)
);
