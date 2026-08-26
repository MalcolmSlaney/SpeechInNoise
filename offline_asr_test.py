"""Tests for offline_asr.py."""

import json
import os
import sqlite3
import tempfile
from unittest import mock

import numpy as np
import scipy.io.wavfile
from absl.testing import absltest
from absl.testing import flagsaver
from absl import flags

import offline_asr

FLAGS = flags.FLAGS


class OfflineASRTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.temp_dir = self.create_tempdir()
        
        # Paths for test dependencies
        self.db_path = os.path.join(self.temp_dir.full_path, 'test_experiments.db')
        self.audiodir = self.temp_dir.full_path
        self.valid_words_path = os.path.join(self.temp_dir.full_path, 'valid_words.json')
        self.prompt_path = os.path.join(self.temp_dir.full_path, 'EnglishPrompt.wav')
        
        # 1. Generate Synthetic Audio Files
        self.target_audio_name = "test_reply"  # DB stores name without .wav
        self.prime_audio_name = "test_prime"
        
        self._generate_synthetic_wav(os.path.join(self.audiodir, f"{self.target_audio_name}.wav"), duration=2.0)
        self._generate_synthetic_wav(os.path.join(self.audiodir, f"{self.prime_audio_name}.wav"), duration=1.0)
        self._generate_synthetic_wav(self.prompt_path, duration=0.5)

        # 2. Setup SQLite Database
        self._create_mock_database()

        # 3. Create Valid Words JSON
        with open(self.valid_words_path, 'w') as f:
            json.dump({"quick": ["hello", "world"], "cnc": ["test", "word"]}, f)

    def _generate_synthetic_wav(self, filepath: str, duration: float = 1.0, sample_rate: int = 22050):
        """Generates a synthetic sine wave (beep) and writes it to disk."""
        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        # Generate a 440 Hz sine wave
        audio_data = (np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
        scipy.io.wavfile.write(filepath, sample_rate, audio_data)

    def _create_mock_database(self):
        """Creates the expected database schema and seeds it with testing data."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, ip TEXT, t TEXT);
            CREATE TABLE audio_trials (id INTEGER PRIMARY KEY, project TEXT, snr INTEGER, lang TEXT, level_number INTEGER, trial_number INTEGER, filename TEXT, answer TEXT, active BOOLEAN);
            CREATE TABLE audio_results (id INTEGER PRIMARY KEY, subject INTEGER, trial INTEGER, reply_filename TEXT, t TEXT);
            CREATE TABLE audio_asr (ref INTEGER PRIMARY KEY, data TEXT);
        """)

        # Seed User
        cursor.execute("INSERT INTO users VALUES (1, 'A1S1', '127.0.0.1', '2023-01-01')")
        
        # Seed Trials (One standard, one needing a prime)
        cursor.execute("INSERT INTO audio_trials VALUES (1, 'quick', 10, 'en', 1, 1, 'f1', 'hello world', 1)")
        cursor.execute("INSERT INTO audio_trials VALUES (2, 'cnc', 10, 'en', 1, 2, 'f2', 'test', 1)")

        # Seed Results (Pointing to the synthetic audio file)
        # Result 101: A normal quick test
        cursor.execute("INSERT INTO audio_results VALUES (101, 1, 1, ?, '2023-01-01')", (self.target_audio_name,))
        # Result 102: A cnc test (triggering priming logic)
        cursor.execute("INSERT INTO audio_results VALUES (102, 1, 2, ?, '2023-01-01')", (self.target_audio_name,))

        conn.commit()
        conn.close()

    def test_get_wav_duration_seconds(self):
        """Tests that the duration is accurately read from the synthetic file."""
        target_path = os.path.join(self.audiodir, f"{self.target_audio_name}.wav")
        duration = offline_asr.get_wav_duration_seconds(target_path)
        self.assertAlmostEqual(duration, 2.0, places=2)

    def test_filter_segment(self):
        """Tests the mathematical rebasing of timestamps for primed segments."""
        segment = {
            'start': 1.5,
            'end': 2.5,
            'words': [{'word': 'test', 'start': 1.6, 'end': 2.0}]
        }
        
        # Prime is 1.0 second long
        filtered = offline_asr.filter_segment(segment, priming_time=1.0)
        
        self.assertIsNotNone(filtered)
        self.assertAlmostEqual(filtered['start'], 0.5)
        self.assertAlmostEqual(filtered['end'], 1.5)
        self.assertAlmostEqual(filtered['words'][0]['start'], 0.6)

    @mock.patch('offline_asr.subprocess.run')
    @mock.patch('offline_asr.asr')
    def test_main_pipeline(self, mock_asr_module, mock_subprocess):
        """Tests the full offline ASR pipeline without invoking real Whisper/ffmpeg."""
        
        # 1. Mock ffmpeg so the test doesn't crash if ffmpeg isn't installed
        def mock_subprocess_side_effect(*args, **kwargs):
            # Extract the output filename (the last argument in the ffmpeg command)
            # The command is passed as an argument list in args[0]
            cmd = args[0]
            output_file = cmd[-1]
            
            # Create a dummy file so os.remove doesn't fail
            with open(output_file, 'w') as f:
                f.write("dummy audio data")
                
            mock_result = mock.MagicMock()
            mock_result.returncode = 0
            return mock_result

        mock_subprocess.side_effect = mock_subprocess_side_effect

        # 2. Mock the Whisper engine's output
        mock_engine = mock.MagicMock()
        mock_engine.recognize.return_value = {
            'text': 'hello world',
            'segments': [{
                'start': 1.5, 
                'end': 2.5,
                'words': [
                    {'word': 'hello', 'start': 1.5, 'end': 2.0},
                    {'word': 'world', 'start': 2.0, 'end': 2.5}
                ]
            }]
        }
        
        # Assign the mock engine to the imported ASR class
        mock_asr_module.WhisperASR.return_value = mock_engine

        # 3. Setup flags to use our synthetic temp files
        with flagsaver.flagsaver(
            dbfile=self.db_path,
            audiodir=self.audiodir,
            language_prompt_file=self.prompt_path,
            valid_words=self.valid_words_path,
            target_projects=['quick', 'cnc'],
            single_word_projects='cnc',
            use_prime=True, # Triggers prime fetching
            debug=True
        ):
            
            # 4. Run the main processing loop
            offline_asr.run_main([])
            
            # 5. Verify the Database was updated correctly
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT ref, data FROM audio_asr ORDER BY ref")
            rows = cursor.fetchall()
            conn.close()
            
            # Both trials (101 and 102) should now have ASR data
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][0], 101)
            self.assertEqual(rows[1][0], 102)
            
            # Verify the JSON was packed correctly
            data_101 = json.loads(rows[0][1])
            self.assertEqual(data_101['text'], 'hello world')
            
            # Verify the mocked recognize method was called
            self.assertTrue(mock_engine.recognize.called)


if __name__ == '__main__':
    absltest.main()
