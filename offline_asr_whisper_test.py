"""Integration test for the Whisper ASR module."""

import os
import re
import urllib.request
from absl.testing import absltest
import numpy as np

# Assuming your 'asr' wrapper module is in the same directory or PYTHONPATH
import asr

class WhisperIntegrationTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        # Use absltest's built-in temp directory management for clean teardown
        self.temp_dir = self.create_tempdir()
        self.audio_url = "https://www.slaney.org/malcolm/tmp/tapestry.wav"
        self.audio_path = os.path.join(self.temp_dir.full_path, "tapestry.wav")
        
        # Download the specific test file
        print(f"Downloading test audio from {self.audio_url}...")
        urllib.request.urlretrieve(self.audio_url, self.audio_path)
        self.expected_text = "A huge tapestry hung in her hallway."

    def _normalize_text(self, text: str) -> str:
        """Removes punctuation and lowercases text for robust comparison."""
        if not text:
            return ""
        return re.sub(r'[^\w\s]', '', text).lower().strip()

    def test_whisper_recognition_accuracy(self):
        """Tests if the Whisper model correctly transcribes the WAV file."""
        # Instantiate the engine using 'base.en' 
        # (You can change this to 'tiny.en' if you want the test to run faster, 
        # though 'base.en' is safer for accuracy validation)
        engine = asr.WhisperASR("base.en")
        
        # Run the actual recognition
        result = engine.recognize(self.audio_path, language="en")
        
        self.assertIsNotNone(result, "ASR result should not be None.")
        self.assertIn('text', result, "ASR result must contain a 'text' key.")
        
        actual_text = result['text']
        
        # Normalize both strings to prevent test flakes from punctuation differences
        normalized_actual = self._normalize_text(actual_text)
        normalized_expected = self._normalize_text(self.expected_text)
        
        self.assertEqual(
            normalized_actual, 
            normalized_expected, 
            f"Expected '{normalized_expected}', but got '{normalized_actual}'"
        )

if __name__ == '__main__':
    absltest.main()
