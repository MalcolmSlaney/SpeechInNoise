import pprint
import sys
from absl import app
from absl import flags

# Import your ASR module
import asr

FLAGS = flags.FLAGS

flags.DEFINE_string(
    'audio_file', 
    None, 
    'Path to the test WAV file.'
)
flags.mark_flag_as_required('audio_file')

flags.DEFINE_string(
    'words', 
    'yes,no,true,false', 
    'Comma-separated list of valid words to force.'
)
flags.DEFINE_string(
    'prompt', 
    '', 
    'Initial prompt to bias the model.'
)
flags.DEFINE_string(
    'model', 
    'tiny.en', 
    'Whisper model to load (default: tiny.en).'
)

# --- Standard single-run penalty flag ---
flags.DEFINE_float(
    'penalty', 
    10.0, 
    'OOV Penalty for the forced model (used if --sweep is False).'
)

# --- New Sweep Flags ---
flags.DEFINE_boolean(
    'sweep',
    False,
    'If True, run a sweep of penalty values instead of a single run.'
)
flags.DEFINE_float(
    'min_penalty',
    0.0,
    'Minimum penalty value for the sweep.'
)
flags.DEFINE_float(
    'max_penalty',
    20.0,
    'Maximum penalty value for the sweep.'
)
flags.DEFINE_integer(
    'num_steps',
    5,
    'Number of steps from min_penalty to max_penalty.'
)

def main(argv):
    # absl passes unparsed arguments to argv. We shouldn't have any if we only use flags.
    if len(argv) > 1:
        raise app.UsageError('Too many command-line arguments.')

    audio_file = FLAGS.audio_file
    valid_words = [w.strip() for w in FLAGS.words.split(",")]
    initial_prompt = FLAGS.prompt
    model_name = FLAGS.model

    print(f"=== Test Configuration ===")
    print(f"Model: {model_name}")
    print(f"Audio File: {audio_file}")
    print(f"Initial Prompt: '{initial_prompt}'")
    print(f"Forced Vocabulary: {valid_words}")
    if FLAGS.sweep:
        print(f"Sweep Mode: {FLAGS.min_penalty} to {FLAGS.max_penalty} in {FLAGS.num_steps} steps")
    else:
        print(f"OOV Penalty: {FLAGS.penalty}")
    print("=" * 50 + "\n")

    # ---------------------------------------------------------
    # 1. Standard Whisper ASR
    # ---------------------------------------------------------
    print("Loading Standard WhisperASR...")
    standard_engine = asr.WhisperASR(model_name)
    print("Running recognition...\n")
    res_standard = standard_engine.recognize(audio_file)
    
    print("--- STANDARD RESULT TEXT ---", res_standard.get("text", "").strip())

    # ---------------------------------------------------------
    # 2. Prompted Whisper ASR
    # ---------------------------------------------------------
    print("-" * 50 + "\n")
    print("Loading PromptedWhisperASR...")
    prompted_engine = asr.PromptedWhisperASR(model_name)
    print("Running recognition...\n")
    res_prompted = prompted_engine.recognize(audio_file, initial_prompt=initial_prompt)
    
    print("--- PROMPTED RESULT TEXT ---", res_prompted.get("text", "").strip())

    # ---------------------------------------------------------
    # 3. Forced Whisper ASR (Single Run or Sweep)
    # ---------------------------------------------------------
    print("-" * 50)
    print("Loading ForcedWhisperASR...")
    forced_engine = asr.ForcedWhisperASR(model_name)
    
    if FLAGS.sweep:
        print(f"Running sweep recognition ({FLAGS.num_steps} steps)...\n")
        
        # Calculate penalty values
        if FLAGS.num_steps > 1:
            step_size = (FLAGS.max_penalty - FLAGS.min_penalty) / (FLAGS.num_steps - 1)
            penalties = [FLAGS.min_penalty + (i * step_size) for i in range(FLAGS.num_steps)]
        else:
            penalties = [FLAGS.min_penalty]
            
        sweep_results = []
        
        for p in penalties:
            try:
                res_forced = forced_engine.recognize(
                    audio_file, 
                    initial_prompt=initial_prompt, 
                    valid_words=valid_words, 
                    oov_penalty=p
                )
                text = res_forced.get("text", "").strip()
                sweep_results.append((p, text))
                print(f"Processed penalty={p:5.2f} -> {text}")
            except Exception as e:
                sweep_results.append((p, f"ERROR: {e}"))
                print(f"Processed penalty={p:5.2f} -> ERROR")
                
        print("\n" + "=" * 50)
        print("--- SWEEP SUMMARY ---")
        for p, text in sweep_results:
            print(f"Penalty: {p:5.2f} | Text: {text}")
        print("=" * 50)
        
    else:
        # Standard Single Run
        print("Running recognition...\n")
        try:
            res_forced = forced_engine.recognize(
                audio_file, 
                initial_prompt=initial_prompt, 
                valid_words=valid_words, 
                oov_penalty=FLAGS.penalty
            )
            
            print("--- FORCED RESULT TEXT ---", res_forced.get("text", "").strip())
            
            print("\n--- FORCED RESULT DETAILED OUTPUT ---")
            # Pretty print the dictionary, but truncate 'segments' if it gets too long
            pprint.pprint(res_forced, depth=3)
            
        except Exception as e:
            print(f"Forced engine failed with error: {e}", file=sys.stderr)


if __name__ == "__main__":
    app.run(main)
