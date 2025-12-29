/* play, next buttons*/
(function() {
  'use strict';
  
  const DOM_IDS = window.ReviewModules.DOM_IDS;
  const BUTTON_STATES = window.ReviewModules.BUTTON_STATES;

  class ButtonManager {
    constructor(domCache, uiUpdater) {
      this.dom = domCache;
      this.ui = uiUpdater;
    }

    getNextButton() {
      return this.dom.get('NEXT_AUDIO_BUTTON');
    }

    getPlaybackButton() {
      return this.dom.get('PLAYBACK_BUTTON');
    }

    enableNextButton(button = null) {
      const nextButton = button || this.getNextButton();
      if (nextButton) {
        nextButton.disabled = false;
        nextButton.style.opacity = BUTTON_STATES.ENABLED_OPACITY;
      }
    }

    disableNextButton(button = null) {
      const nextButton = button || this.getNextButton();
      if (nextButton) {
        nextButton.disabled = true;
        nextButton.style.opacity = BUTTON_STATES.DISABLED_OPACITY;
      }
    }

    resetPlaybackButton(button, ...classes) {
      if (!button) return;

      const playbackButtonClasses = [
        'play', 'playable', 'pause', 'load', 'stop', 'record', 'done', 'error', 'ing'
      ];

      for (const className of playbackButtonClasses) {
        button.classList.remove(className);
      }

      for (const className of classes) {
        button.classList.add(className);
      }
    }
  }

  window.ReviewModules.ButtonManager = ButtonManager;
})();

