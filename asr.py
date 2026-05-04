"""Whisper ASR wrapper classes used by the SpeechInNoise project.

This module provides two ASR engine wrappers around OpenAI Whisper:
`WhisperASR` for standard transcription and `PromptedWhisperASR` for
transcription with an optional initial prompt. Each engine exposes a
`recognize` method that returns the raw Whisper output augmented with
engine metadata.
"""

from typing import Any, List, Union

# Documentation seems to be at:
#   https://whisper-api.com/docs/transcription-options/#setting-the-language

import subprocess
import torch
import whisper
from whisper.normalizers import EnglishTextNormalizer
from whisper.decoding import LogitFilter, DecodingTask


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
                  initial_prompt: str = '',
                  valid_words: List[str] = None # Ignored for this class
                  ) -> dict[str, Any]:
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
                  initial_prompt: str = '',
                  valid_words: List[str] = None # Ignored for this class
                  ) -> dict[str, Any]:
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


class OOVLogitFilter(LogitFilter):
    def __init__(self, allowed_token_ids, penalty, timestamp_begin=None):
        self.allowed_token_ids = allowed_token_ids
        self.penalty = penalty
        self.timestamp_begin = timestamp_begin

    def apply(self, logits: torch.Tensor, tokens: torch.Tensor):
        # logits shape: (batch_size, vocab_size)
        mask = torch.ones_like(logits[0], dtype=torch.bool)
        
        # Unmask the allowed vocabulary tokens
        mask[self.allowed_token_ids] = False
        
        # Unmask timestamp tokens so we don't break Whisper's timing/segmentation
        if self.timestamp_begin is not None and self.timestamp_begin < logits.shape[-1]:
            mask[self.timestamp_begin:] = False
            
        # Apply the penalty to everything else
        logits[:, mask] -= self.penalty

class ForcedWhisperASR(WhisperASR): # Assuming WhisperASR is your base class
    def recognize(self, audio_path, initial_prompt='', valid_words=None, oov_penalty=10.0):
        options = {"initial_prompt": initial_prompt, 
                   "word_timestamps": True,
                   "fp16": False}
        
        if valid_words:
            # Tokenize the valid words using the whisper tokenizer
            tokenizer = whisper.tokenizer.get_tokenizer(
                self.model.is_multilingual, language="en"
            )
            
            allowed_token_ids = set()
            for word in valid_words:
                # Whisper tokens often include a leading space; it's safest to allow both
                allowed_token_ids.update(tokenizer.encode(" " + word.strip()))
                allowed_token_ids.update(tokenizer.encode(word.strip()))
                
            # Add essential structural tokens (End of text, Start of text, no speech etc.)
            for token in [tokenizer.eot, tokenizer.sot, getattr(tokenizer, 'no_speech', None)]:
                if token is not None:
                    allowed_token_ids.add(token)
            
            timestamp_begin = getattr(tokenizer, 'timestamp_begin', None)
            
            # Create our custom filter
            custom_filter = OOVLogitFilter(
                allowed_token_ids=list(allowed_token_ids), 
                penalty=oov_penalty,
                timestamp_begin=timestamp_begin
            )
            
            # Temporarily inject the filter into Whisper's DecodingTask __init__
            original_init = DecodingTask.__init__
            
            def hooked_init(task_self, task_model, task_options):
                # Call the original __init__ which sets up task_self.logit_filters
                original_init(task_self, task_model, task_options)
                
                # Append our custom filter to the pipeline
                if hasattr(task_self, 'logit_filters'):
                    task_self.logit_filters.append(custom_filter)
                else:   
                    print("Warning: DecodingTask has no logit_filters attribute. OOV filtering may not work.")

            DecodingTask.__init__ = hooked_init
            
            try:
                # Transcribe with the hooked filter
                result = self.model.transcribe(audio_path, **options)
                # print(f"Applied OOV filter with {len(allowed_token_ids)} allowed tokens and penalty {oov_penalty}")
                # print(f' Transcribe returned: {result}')
            finally:
                # Always restore the original function so we don't permanently break it
                DecodingTask.__init__ = original_init
                
            return result
            
        # Fallback if no valid_words were passed
        return self.model.transcribe(audio_path, **options)