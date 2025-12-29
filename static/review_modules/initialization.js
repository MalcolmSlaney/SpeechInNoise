/* set up UI */

(function() {
  'use strict';
  
  const DOM_IDS = window.ReviewModules.DOM_IDS;

  class InitializationManager {
    constructor(domCache, buttonManager, exitManager, audioEventHandler) {
      this.dom = domCache;
      this.buttons = buttonManager;
      this.exit = exitManager;
      this.audioEvents = audioEventHandler;
    }

    setupButtons(context) {
      if (this.buttons) {
        context.nextButton = this.buttons.getNextButton();
        context.playbackButton = this.buttons.getPlaybackButton();
      } else {
        if (!context.nextButton) {
          context.nextButton = document.getElementById('next-audio');
        }
        context.playbackButton = document.getElementById('playback');
      }

      if (context.nextButton && !context.nextButton.hasAttribute('data-listener-attached')) {
        context.nextButton.addEventListener('click', () => {
          context._reviewSubmitted = true;
          context._hideExitWarning();
          context.result(0);
        });
        context.nextButton.setAttribute('data-listener-attached', 'true');
      }

      if (context.playbackButton && !context.playbackButton.hasAttribute('data-listener-attached')) {
        context.resetPlaybackButton('play');
        context.playbackButton.addEventListener('click', () => {
          context._handlePlaybackButtonClick();
        });
        context.playbackButton.setAttribute('data-listener-attached', 'true');
      }

      this._setupAllNoneButtons();
    }

    _setupAllNoneButtons() {
      const resultAllButton = document.getElementById('result-all');
      const resultNoneButton = document.getElementById('result-none');

      if (resultAllButton && !resultAllButton.hasAttribute('data-listener-attached')) {
        resultAllButton.addEventListener('click', () => {
          Array.from(document.querySelectorAll('.annotation-on')).forEach(x => {
            x.checked = true;
          });
        });
        resultAllButton.setAttribute('data-listener-attached', 'true');
      }

      if (resultNoneButton && !resultNoneButton.hasAttribute('data-listener-attached')) {
        resultNoneButton.addEventListener('click', () => {
          Array.from(document.querySelectorAll('.annotation-off')).forEach(x => {
            x.checked = true;
          });
        });
        resultNoneButton.setAttribute('data-listener-attached', 'true');
      }
    }
  }

  window.ReviewModules.InitializationManager = InitializationManager;
})();

