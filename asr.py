"""Whisper ASR wrapper classes used by the SpeechInNoise project.

This module provides two ASR engine wrappers around OpenAI Whisper:
`WhisperASR` for standard transcription and `PromptedWhisperASR` for
transcription with an optional initial prompt. Each engine exposes a
`recognize` method that returns the raw Whisper output augmented with
engine metadata.
"""

from typing import Any, Union

# Documentation seems to be at:
#   https://whisper-api.com/docs/transcription-options/#setting-the-language
import whisper, subprocess
from whisper.normalizers import EnglishTextNormalizer

assert not subprocess.run(
    ["which", "ffmpeg"], stdout=subprocess.DEVNULL).returncode

# Whisper documentation at https://github.com/openai/whisper

whisper_normalizer = EnglishTextNormalizer()

class WhisperASR:
    """Standard Whisper ASR wrapper.

    This class loads a Whisper model and exposes a simple recognize interface
    for transcribing audio files with word timestamps enabled.
    """

    def __init__(self, model_name: str = "small.en"):
        """Initialize the WhisperASR model.

        Args:
            model_name: The Whisper model name to load, such as "small.en".
        """
        self.model = whisper.load_model(model_name)
        self.meta = {"model_name": model_name, "model_type": "default"}

    def recognize(self,
                  audio_path: str,
                  language: str = 'en',
                  initial_prompt: str = '') -> dict[str, Any]:
        """Transcribe an audio file using Whisper.

        Args:
            audio_path: Path to the audio file to transcribe.
            language: Language code to use for transcription.
            initial_prompt: Optional initial prompt to bias transcription.

        Returns:
            A dictionary containing Whisper transcription results merged with
            engine metadata.
        """
        res = self.model.transcribe(audio_path, word_timestamps=True,
                                    language=language,
                                    initial_prompt=initial_prompt,
                                    fp16=False)
        return {**res, **self.meta}


class PromptedWhisperASR:
    """Whisper ASR wrapper that supports prompted transcription.

    This class is intended for use cases where an initial prompt can improve
    accuracy by biasing Whisper toward the expected content.

    Not sure this subclass is still needed as acoustic priminng and prompting
    are the same in both cases.
    """

    def __init__(self, model_name: str = "base.en"):
        """Initialize the PromptedWhisperASR model.

        Args:
            model_name: The Whisper model name to load, such as "base.en".
        """
        self.model = whisper.load_model(model_name)
        self.meta = {"model_name": model_name, "model_type": "prompted"}

    def recognize(self,
                  audio_path: str,
                  language: str = 'en',
                  initial_prompt: str = '') -> dict[str, Any]:
        """Transcribe an audio file using Whisper with an initial prompt.

        Args:
            audio_path: Path to the audio file to transcribe.
            language: Language code to use for transcription.
            initial_prompt: Optional initial prompt to bias transcription.

        Returns:
            A dictionary containing Whisper transcription results merged with
            engine metadata.
        """
        res = self.model.transcribe(
                audio_path, word_timestamps=True,
                initial_prompt=initial_prompt,
                language=language,
                fp16=False)
        return {**res, **self.meta}


WhisperASREngine = Union[WhisperASR, PromptedWhisperASR]
