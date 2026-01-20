/* get next audio file*/

(function() {
  'use strict';

  class LoadHandler {
    constructor(domCache, stateManager, uiUpdater, audioManager, waveformManager, annotationManager, audioPrefetcher) {
      this.dom = domCache;
      this.state = stateManager;
      this.ui = uiUpdater;
      this.audio = audioManager;
      this.waveform = waveformManager;
      this.annotations = annotationManager;
      this.prefetcher = audioPrefetcher;
    }

    async handleFileLoad(data, context) {
      this._resetState(data, context);

      if (!data.cur || data.cur === '') {
        return this._handleNoMoreFiles(data, context);
      }

      if (!this._validateFileData(data, context)) {
        return;
      }

      this._updateUI(data);

      const audioElement = this.audio.getAudioElement();
      if (audioElement) {
        this.audio.resetAudioElement(context.playbackButton, context._audioPlayed);
        this.audio.clearAnnotationUI();
        context.resetAudioProgress();
        if (context.playbackButton) {
          context.resetPlaybackButton('play');
        }
        context.disableNextButton();
      }

      this._createAnnotationUI(data);

      await this._prefetchAndSetupAudio(data, audioElement, context);
      
      // Ensure annotation listeners are set up ( if page was reloaded)
      if (context.initializationManager) {
        context.initializationManager._setupAnnotationListeners(context);
      }
      
      // Update button state based on audio playback and annotation completion
      // Use a timeout to ensure annotations are fully rendered
      if (context.audioEventHandler && context.nextButton) {
        setTimeout(() => {
          context.audioEventHandler._updateNextButtonState(context.nextButton, context);
        }, 200);
      } else if (context.nextButton) {
        // disable button if we can't check state
        context.disableNextButton();
      }
    }

    _resetState(data, context) {
      if (this.state) {
        this.state.resetForNewFile(data);
        context._audioPlayed = this.state.hasAudioPlayed();
        context._currentFileId = this.state.getCurrentFileId();
      } else {
        const alreadyPlayed = data.already_played === true || data.already_played === 'true';
        context._audioPlayed = alreadyPlayed;
        context._currentFileId = data.file_id || null;
      }

      context._reviewSubmitted = false;
      context._hideExitWarning();

      if (this.audio) {
        this.audio.resetUnclearCheckbox();
      }
    }

    _handleNoMoreFiles(data, context) {
      context._audioPlayed = false;
      context._reviewSubmitted = false;
      this._handlePreviousError(context);
      context.showThankYouPage(data);
    }

    _validateFileData(data, context) {
      if (!data.cur || data.cur === '' || data.cur === context.project) {
        console.error('Invalid or missing audio URL in data:', data);
        context.showThankYouPage(data);
        return false;
      }

      if (!data.answer) {
        console.warn('No answer in data, setting default empty array');
        data.answer = ['', ''];
      }

      return true;
    }

    _updateUI(data) {
      if (this.ui) {
        this.ui.updateHeaderFields(data);
        this.ui.updateCurrentFilename(data.cur);
        if (data.name) {
          this.ui.updateLabelerName(data.name);
        }
      }
    }

    _createAnnotationUI(data) {
      if (data.answer && data.answer[0] && typeof data.answer[0] === 'string' && data.answer[0].trim() !== '') {
        //console.log('Creating new annotation checkboxes:', data.answer[0]);
        try {
          if (this.annotations) {
            this.annotations.createAnnotationUI(data.answer[0]);
            this.annotations.validateAnnotationUI((count) => {
              if (count === 0) {
                console.error('No checkboxes created!');
              }
            });
          } else {
            const holder = this.dom.querySelector('#aux-data');
            if (holder) {
              console.warn('AnnotationManager not available, using fallback');
            }
          }
        } catch (e) {
          console.error('Error creating annotation UI:', e);
        }
      }
    }

    async _prefetchAndSetupAudio(data, audioElement, context) {
      if (!audioElement || !data.cur || data.cur === '') return;

      //console.log('Prefetching new audio URL:', data.cur);

      if (this.prefetcher) {
        await this.prefetcher.prefetchWithFallback(
          data.cur,
          (blobUrl) => {
            context.src(blobUrl);
            this._createWaveform(audioElement, context);
          },
          (originalUrl) => {
            context.src(originalUrl);
            this._createWaveform(audioElement, context);
          }
        );
      } else {
        fetch(data.cur)
          .then(response => response.arrayBuffer())
          .then(buffer => {
            const blob = new Blob([buffer], { type: 'audio/wav' });
            const blobUrl = URL.createObjectURL(blob);
            context.src(blobUrl);
            this._createWaveform(audioElement, context);
          })
          .catch(error => {
            console.error('Error prefetching new audio:', error);
            context.src(data.cur);
            this._createWaveform(audioElement, context);
          });
      }
    }

    _createWaveform(audioElement, context) {
      if (this.waveform) {
        this.waveform.destroyWaveform(context.waveform);
        context.waveform = this.waveform.createWaveform(
          audioElement,
          context.playbackButton,
          context._audioPlayed
        );
        
        if (context.initializationManager) {
          setTimeout(() => {
            if (context.audioEventHandler && context.nextButton) {
              context.audioEventHandler._updateNextButtonState(context.nextButton, context);
            }
          }, 100);
        }
      }
    }

    _handlePreviousError(context) {
      if (context._lastError) {
        const errorMsg = context._lastError.includes('FOREIGN KEY')
          ? 'Warning: The previous annotation may not have been saved.'
          : `Warning: ${context._lastError}`;
        setTimeout(() => console.warn(errorMsg), 100);
        context._lastError = null;
      }
    }
  }

  window.ReviewModules.LoadHandler = LoadHandler;
})();

