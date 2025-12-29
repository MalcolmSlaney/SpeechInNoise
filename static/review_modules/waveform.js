/**
 * waveform of audio files
 */

(function() {
  'use strict';
  
  const DOM_IDS = window.ReviewModules.DOM_IDS;

  class WaveformManager {
  constructor(domCache, SimpleWaveformClass, uiUpdater) {
    this.dom = domCache;
    this.SimpleWaveform = SimpleWaveformClass;
    this.ui = uiUpdater;
  }

  /**
   * Create and setup a new waveform for an audio element.
   * @param {HTMLElement} audioElement - The audio element
   * @param {HTMLElement} playButton - The play button element
   * @param {boolean} audioAlreadyPlayed - Whether audio has already been played
   * @param {Function} onLoadedCallback - Optional callback when waveform loads
   * @returns {SimpleWaveform|null} The created waveform instance
   */
  createWaveform(audioElement, playButton, audioAlreadyPlayed = false, onLoadedCallback = null) {
    if (!audioElement) {
      console.warn('Cannot create waveform - audio element missing');
      return null;
    }

    const waveformCanvas = this.dom.get('WAVEFORM_CANVAS');
    if (!waveformCanvas) {
      console.warn('Cannot create waveform - canvas missing');
      return null;
    }

    // Clear the canvas first
    const ctx = waveformCanvas.getContext('2d');
    if (ctx) {
      ctx.clearRect(0, 0, waveformCanvas.width, waveformCanvas.height);
    }

    // Create waveform - it will load when audio is ready
    console.log('Creating new waveform');
    const waveform = new this.SimpleWaveform(audioElement, waveformCanvas);

    // Set callback to enable play button when waveform finishes loading
    // Only enable if audio hasn't already been played
    waveform.onLoaded = () => {
      if (playButton && !audioAlreadyPlayed) {
        this.ui.enablePlayButton(playButton);
        console.log('Play button enabled - waveform loaded');
      } else if (playButton && audioAlreadyPlayed) {
        console.log('Play button remains disabled - audio has already been played');
      }
      // Call custom callback if provided
      if (onLoadedCallback) {
        onLoadedCallback(waveform);
      }
    };

    // If waveform is already loaded (e.g., audio was already ready), enable button immediately
    // Only if audio hasn't already been played
    if (waveform.isLoaded && playButton && !audioAlreadyPlayed) {
      this.ui.enablePlayButton(playButton);
    } else if (waveform.isLoaded && playButton && audioAlreadyPlayed) {
      // Waveform loaded but audio already played - keep disabled
      this.ui.disablePlayButton(playButton, 'audio has already been played');
    }

    return waveform;
  }

  /**
   * Destroy an existing waveform instance.
   * @param {SimpleWaveform} waveform - The waveform instance to destroy
   */
  destroyWaveform(waveform) {
    if (!waveform) return;

    try {
      if (typeof waveform.destroy === 'function') {
        waveform.destroy();
      }
    } catch (e) {
      console.warn('Error destroying waveform:', e);
    }
  }

  /**
   * Reset waveform progress.
   * @param {SimpleWaveform} waveform - The waveform instance
   */
  resetProgress(waveform) {
    if (waveform && typeof waveform.resetProgress === 'function') {
      waveform.resetProgress();
    }
  }
  }

  window.ReviewModules.WaveformManager = WaveformManager;
})();

