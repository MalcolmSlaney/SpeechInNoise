import json
import os
import pathlib
import sqlite3
from tqdm import tqdm

import asr

basename = pathlib.Path(__file__).parents[0]

def audio_queue(con: sqlite3.Connection):
    cur = con.execute(
            "SELECT audio_results.id, reply_filename, answer "
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

def main(asr_engine: asr.WhisperASREngine, db_file: str):
    con = sqlite3.connect(db_file)
    for rowid, fname, ans in tqdm(audio_queue(con)):
        try:
            update(con, rowid, asr_engine(str(basename / "uploads" / fname)))
        except RuntimeError as e:
            # Code to handle the exception
            print(f"An error occurred: {e}")
            print('While processing', str(basename / "uploads" / fname))

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
                        default=os.path.join(basename, "experiments.db"), 
                        help="Which SQLite3 database file to process")
    parser.add_argument(
            "--prompted", dest="asr", default="WhisperASR",
            action="store_const", const="PromptedWhisperASR", help=(
                "use the correct answer as the model prompt; can help accuracy "
                "but can also bias results towards correct"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.force:
        model_type = "default" if args.asr == "WhisperASR" else "prompted"
        deduplicate(model_name=args.model, model_type=model_type)
    
    main(getattr(asr, args.asr)(args.model), args.dbfile)

