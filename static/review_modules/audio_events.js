/**
 * audio event listeners for playback, progress, and state changes.
 */

(function() {
  'use strict';

  class AudioEventHandler {
    constructor(domCache, uiUpdater, stateManager, apiClient) {
      this.dom = domCache;
      this.ui = uiUpdater;
      this.state = stateManager;
      this.api = apiClient;
    }

    /**
     * Set up all audio event handlers.
     * @param {HTMLAudioElement} audioElement - The audio element
     * @param {HTMLElement} playbackButton - The play button
     * @param {HTMLElement} nextButton - The next button
     * @param {SimpleWaveform} waveform - The waveform instance
     * @param {Object} context - ReviewAudio instance context
     */
    setupEventHandlers(audioElement, playbackButton, nextButton, waveform, context) {
      if (!audioElement) return;

      // Handle play event
      audioElement.addEventListener('play', () => {
        this._handlePlay(audioElement, playbackButton, nextButton, context);
      });

      // Handle ended event
      audioElement.addEventListener('ended', () => {
        this._handleEnded(playbackButton, nextButton);
      });

      // Handle timeupdate for waveform progress
      audioElement.addEventListener('timeupdate', () => {
        this._handleTimeUpdate(audioElement, waveform);
      });

      // Prevent pausing 
      audioElement.addEventListener('pause', (e) => {
        this._handlePause(audioElement, nextButton, playbackButton);
      });
    }

    /**
     * Handle audio play event.
     * @private
     */
    _handlePlay(audioElement, playbackButton, nextButton, context) {
      // Mark that audio has been played
      context._audioPlayed = true;
      if (this.state) {
        this.state.markAudioPlayed();
      }

      // Disable next button during playback
      this._disableNextButton(nextButton);

      // Update play button to show pause state (but disabled)
      if (playbackButton) {
        context.resetPlaybackButton('pause');
      }

      // Track that audio has been played in the database
      if (context._currentFileId && this.api) {
        this.api.trackAudioPlayed(context._currentFileId);
      } else if (context._currentFileId) {
        context._trackAudioPlayed(context._currentFileId);
      }
    }

    /**
     * Handle audio ended event.
     * @private
     */
    _handleEnded(playbackButton, nextButton) {
      // Enable next button when audio ends
      this._enableNextButton(nextButton);

      // Disable play button so it can't be played again
      if (playbackButton) {
        playbackButton.disabled = true;
        playbackButton.style.opacity = '0.5';
        playbackButton.style.cursor = 'not-allowed';
      }
    }

    /**
     * Handle timeupdate for waveform progress.
     * @private
     */
    _handleTimeUpdate(audioElement, waveform) {
      if (audioElement.duration && waveform) {
        waveform.updateProgress(audioElement.currentTime, audioElement.duration);
      }
    }

    /**
     * Handle pause event - prevent pausing unless audio has ended.
     * @private
     */
    _handlePause(audioElement, nextButton, playbackButton) {
      if (!audioElement.ended) {
        // Prevent pause - immediately resume
        console.log('Pause prevented - resuming playback');
        audioElement.play();
      } else {
        // Audio ended - allow pause and enable next button
        this._enableNextButton(nextButton);
        if (playbackButton) {
          // Reset to play button state altho resetPlaybackButton is on context, not this
        }
      }
    }

    /**
     * Enable next button.
     * @private
     */
    _enableNextButton(nextButton) {
      if (nextButton) {
        nextButton.disabled = false;
        nextButton.style.opacity = '1';
      }
    }

    /**
     * Disable next button.
     * @private
     */
    _disableNextButton(nextButton) {
      if (nextButton) {
        nextButton.disabled = true;
        nextButton.style.opacity = '0.5';
      }
    }
  }

  window.ReviewModules.AudioEventHandler = AudioEventHandler;
})();

