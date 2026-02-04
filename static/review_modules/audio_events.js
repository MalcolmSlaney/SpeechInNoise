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


    setupEventHandlers(audioElement, playbackButton, nextButton, waveform, context) {
      if (!audioElement) return;

      // Handle play event
      audioElement.addEventListener('play', () => {
        this._handlePlay(audioElement, playbackButton, nextButton, context);
      });

      // Handle ended event
      audioElement.addEventListener('ended', () => {
        this._handleEnded(playbackButton, nextButton, context);
      });

      // Handle timeupdate for waveform progress
      audioElement.addEventListener('timeupdate', () => {
        const currentWaveform = context.waveform || waveform;
        this._handleTimeUpdate(audioElement, currentWaveform);
      });

      // Prevent pausing 
      audioElement.addEventListener('pause', (e) => {
        this._handlePause(audioElement, nextButton, playbackButton);
      });
    }

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

    _handleEnded(playbackButton, nextButton, context) {
      this._updateNextButtonState(nextButton, context);

      if (playbackButton) {
        playbackButton.disabled = true;
        playbackButton.style.opacity = '0.5';
        playbackButton.style.cursor = 'not-allowed';
        if (context && context.resetPlaybackButton) {
          context.resetPlaybackButton('play');
        }
      }
    }

    _handleTimeUpdate(audioElement, waveform) {
      if (audioElement.duration && waveform) {
        waveform.updateProgress(audioElement.currentTime, audioElement.duration);
      }
    }

    _handlePause(audioElement, nextButton, playbackButton) {
      if (!audioElement.ended) {
        audioElement.play();
      } else {
        this._enableNextButton(nextButton);
      }
    }

    _enableNextButton(nextButton) {
      if (this.ui && this.ui.enableNextButton) {
        this.ui.enableNextButton(nextButton);
      } else if (nextButton) {
        nextButton.disabled = false;
        nextButton.style.opacity = '1';
      }
    }

    _disableNextButton(nextButton) {
      if (this.ui && this.ui.disableNextButton) {
        this.ui.disableNextButton(nextButton);
      } else if (nextButton) {
        nextButton.disabled = true;
        nextButton.style.opacity = '0.5';
      }
    }

    _updateNextButtonState(nextButton, context) {
      if (!nextButton) return;
      
      let audioElement = null;
      if (context.audioManager) {
        audioElement = context.audioManager.getAudioElement();
      } else {
        audioElement = document.getElementById('playing');
      }


      const isCurrentlyPlaying = audioElement && !audioElement.paused && !audioElement.ended;
      const audioFinished = (audioElement && audioElement.ended) || 
                           (context._audioPlayed && !isCurrentlyPlaying && (!audioElement || audioElement.ended || audioElement.paused));
      const allScored = this._validateAllAnnotationsScored(context);
      
      if (audioFinished && allScored) {
        this._enableNextButton(nextButton);
      } else {
        this._disableNextButton(nextButton);
      }
    }

    _validateAllAnnotationsScored(context) {
      const radioGroups = document.querySelectorAll('input[type="radio"].annotation');
      if (radioGroups.length === 0) {
        return true;
      }

      const groupNames = new Set();
      radioGroups.forEach(radio => {
        if (radio.name) {
          groupNames.add(radio.name);
        }
      });

      for (const groupName of groupNames) {
        const groupRadios = document.querySelectorAll(`input[name="${groupName}"].annotation`);
        const hasSelection = Array.from(groupRadios).some(radio => radio.checked);
        if (!hasSelection) {
          return false;
        }
      }

      return true;
    }
  }

  window.ReviewModules.AudioEventHandler = AudioEventHandler;
})();

