/* waveform of audio files */

(function() {
  'use strict';
  
  const DOM_IDS = window.ReviewModules.DOM_IDS;

  class WaveformManager {
  constructor(domCache, SimpleWaveformClass, uiUpdater) {
    this.dom = domCache;
    this.SimpleWaveform = SimpleWaveformClass;
    this.ui = uiUpdater;
  }

  createWaveform(audioElement, playButton, audioAlreadyPlayed = false, onLoadedCallback = null) {
    if (!audioElement) return null;

    const waveformCanvas = this.dom.get('WAVEFORM_CANVAS');
    if (!waveformCanvas) return null;

    const ctx = waveformCanvas.getContext('2d');
    ctx.clearRect(0, 0, waveformCanvas.width, waveformCanvas.height);

    const waveform = new this.SimpleWaveform(audioElement, waveformCanvas);

    waveform.onLoaded = () => {
      if (playButton && !audioAlreadyPlayed) {
        this.ui.enablePlayButton(playButton);
      }
      if (onLoadedCallback) {
        onLoadedCallback(waveform);
      }
    };

    if (waveform.isLoaded && playButton && !audioAlreadyPlayed) {
      this.ui.enablePlayButton(playButton);
    } else if (waveform.isLoaded && playButton && audioAlreadyPlayed) {
      this.ui.disablePlayButton(playButton, 'audio has already been played');
    }

    return waveform;
  }

  destroyWaveform(waveform) {
    if (!waveform) return;
    if (waveform.destroy) {
      waveform.destroy();
    }
  }

  resetProgress(waveform) {
    if (waveform && waveform.resetProgress) {
      waveform.resetProgress();
    }
  }
  }

  window.ReviewModules.WaveformManager = WaveformManager;
})();

