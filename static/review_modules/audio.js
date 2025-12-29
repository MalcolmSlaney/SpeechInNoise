/* audio player */
(function() {
  'use strict';
  
  const DOM_IDS = window.ReviewModules.DOM_IDS;
  const BUTTON_STATES = window.ReviewModules.BUTTON_STATES;

  class AudioManager {
  constructor(domCache, uiUpdater) {
    this.dom = domCache;
    this.ui = uiUpdater;
    this.handleAudioError = null;
    this.handleAudioLoaded = null;
  }

  getAudioElement() {
    return this.dom.get('AUDIO_ELEMENT');
  }

  resetAudioElement(playButton, audioAlreadyPlayed = false) {
    const audioElement = this.getAudioElement();
    if (!audioElement) return;

    audioElement.pause();
    audioElement.currentTime = 0;

    if (playButton) {
      if (audioAlreadyPlayed) {
        this.ui.disablePlayButton(playButton, 'audio has already been played');
      } else {
        this.ui.disablePlayButton(playButton, 'waiting for waveform to load');
      }
    }

    if (this.handleAudioError) {
      audioElement.removeEventListener('error', this.handleAudioError);
    }
    if (this.handleAudioLoaded) {
      audioElement.removeEventListener('canplaythrough', this.handleAudioLoaded);
    }

    this.handleAudioError = (errorEvent) => {
      console.error('Audio loading error:', errorEvent, 'source URL:', audioElement.src);
      console.error('Error details:', {
        error: errorEvent.type,
        networkState: audioElement.networkState,
        readyState: audioElement.readyState,
        src: audioElement.src
      });
      alert('Audio file not accessible - check console for details');
    };

    this.handleAudioLoaded = () => {
      console.log('Audio loaded successfully:', audioElement.src);
    };

    audioElement.addEventListener('error', this.handleAudioError);
    audioElement.addEventListener('canplaythrough', this.handleAudioLoaded);
  }

  clearAnnotationUI() {
    const holder = this.dom.querySelector('#aux-data');
    if (!holder) return;

    const existing = holder.querySelector('.options-case');
    if (existing) {
      console.log('Removing old annotation checkboxes container');
      existing.remove();
    }

    const oldAnnotations = holder.querySelectorAll('.annotation');
    oldAnnotations.forEach(el => {
      console.log('Removing stray annotation element:', el);
      el.remove();
    });
  }

  resetUnclearCheckbox() {
    const unclearCheckbox = this.dom.get('UNCLEAR_CHECKBOX');
    if (unclearCheckbox) {
      unclearCheckbox.checked = false;
    }
  }
  }

  window.ReviewModules.AudioManager = AudioManager;
})();

