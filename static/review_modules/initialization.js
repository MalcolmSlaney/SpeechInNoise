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
        this._setupAnnotationListeners(context);
        
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

    _setupAnnotationListeners(context) {
      // Remove existing listener if any to avoid duplicates
      if (this._annotationChangeHandler) {
        document.removeEventListener('change', this._annotationChangeHandler);
      }
      
      const updateButtonState = () => {
        if (this.audioEvents && context.nextButton) {
          this.audioEvents._updateNextButtonState(context.nextButton, context);
        }
      };

      this._annotationChangeHandler = (e) => {
        if (e.target && e.target.classList.contains('annotation')) {
          updateButtonState();
        }
      };
      
      document.addEventListener('change', this._annotationChangeHandler);

      const resultAllButton = document.getElementById('result-all');
      const resultNoneButton = document.getElementById('result-none');
      
      if (resultAllButton) {
        resultAllButton.addEventListener('click', () => {
          setTimeout(updateButtonState, 10);
        });
      }
      
      if (resultNoneButton) {
        resultNoneButton.addEventListener('click', () => {
          setTimeout(updateButtonState, 10);
        });
      }
    }

    _validateAllAnnotationsScored() {
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

