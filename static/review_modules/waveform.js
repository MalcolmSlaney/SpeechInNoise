/* waveform of audio files 
* Sometimes patients were quiet before answering. Showing the waveform helps
* reviewers know whether a response is coming, and how long they will need to wait before advancing.
*/

(function() {
  'use strict';

  // Shared AudioContext to avoid creating multiple instances
  let sharedAudioContext = null;

  function getAudioContext() {
    if (!sharedAudioContext) {
      sharedAudioContext = new (window.AudioContext || window.webkitAudioContext)();
      sharedAudioContext.addEventListener('statechange', () => {
        if (sharedAudioContext.state === 'suspended') {
          sharedAudioContext.resume().catch(e => console.warn('Could not resume AudioContext:', e));
        }
      });
    }
    if (sharedAudioContext.state === 'suspended') {
      sharedAudioContext.resume().catch(e => console.warn('Could not resume AudioContext:', e));
    }
    return sharedAudioContext;
  }

  class SimpleWaveform {
    constructor(audioElement, canvasElement) {
      this.audio = audioElement
      this.canvas = canvasElement
      this.ctx = canvasElement.getContext('2d')
      this.waveformData = []
      this.isLoaded = false
      this.currentProgress = 0
      this._loadWaveformAbortController = null

      // Remove any existing listener before adding to avoid duplicates
      this.audio.removeEventListener('loadeddata', this._loadWaveformHandler);
      this._loadWaveformHandler = () => this.loadWaveform();
      this.audio.addEventListener('loadeddata', this._loadWaveformHandler);

      this.drawEmpty()
    }

    destroy() {
      if (this._loadWaveformAbortController) {
        this._loadWaveformAbortController.abort();
        this._loadWaveformAbortController = null;
      }
      if (this._loadWaveformHandler) {
        this.audio.removeEventListener('loadeddata', this._loadWaveformHandler);
        this._loadWaveformHandler = null;
      }
      if (this.ctx) {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
      }
    }

    async loadWaveform() {
      if (this._loadWaveformAbortController) {
        this._loadWaveformAbortController.abort();
      }
      this._loadWaveformAbortController = new AbortController();

      try {
        const audioContext = getAudioContext();
        const response = await fetch(this.audio.src, { signal: this._loadWaveformAbortController.signal });
        const audioBuffer = await audioContext.decodeAudioData(await response.arrayBuffer());
        this.waveformData = this.extractWaveformFromBuffer(audioBuffer);
        this.isLoaded = true;
        this.draw();
        if (this.onLoaded) this.onLoaded();
      } catch (error) {
        if (error.name === 'AbortError') return;
        // Fall back to dummy data if Web Audio API fails
        this.waveformData = this.createDummyData();
        this.isLoaded = true;
        this.draw();
        if (this.onLoaded) this.onLoaded();
      } finally {
        this._loadWaveformAbortController = null;
      }
    }

    extractWaveformFromBuffer(audioBuffer) {
      const waveform = []
      const targetBars = 200
      const channelData = audioBuffer.getChannelData(0)
      const samplesPerBar = Math.floor(channelData.length / targetBars)

      for (let i = 0; i < targetBars; i++) {
        const startSample = i * samplesPerBar
        const endSample = Math.min(startSample + samplesPerBar, channelData.length)
        let sumAbs = 0
        for (let j = startSample; j < endSample; j++) {
          sumAbs += Math.abs(channelData[j])
        }
        const meanAbs = sumAbs / (endSample - startSample)
        // Compress loud bars; treat very quiet as silence
        waveform.push(meanAbs > 0.005 ? Math.pow(meanAbs, 0.6) : 0)
      }
      return waveform
    }

    createDummyData() {
      const dummy = []
      for (let i = 0; i < 200; i++) {
        if (i < 30 || i > 170 || (i > 80 && i < 90) || (i > 120 && i < 130)) {
          dummy.push(0)
        } else {
          dummy.push(Math.max(0, Math.sin(i * 0.05) * 0.3 + Math.random() * 0.2))
        }
      }
      return dummy
    }

    drawEmpty() {
      const { canvas, ctx } = this
      const centerY = canvas.height / 2
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      ctx.strokeStyle = '#ddd'
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(0, centerY)
      ctx.lineTo(canvas.width, centerY)
      ctx.stroke()
      ctx.fillStyle = '#999'
      ctx.font = '12px Arial'
      ctx.textAlign = 'center'
      ctx.fillText('Waveform will appear when audio loads', canvas.width / 2, centerY)
    }

    draw() {
      if (!this.isLoaded || !this.waveformData.length) return
      const { canvas, ctx } = this
      const centerY = canvas.height / 2
      const barWidth = canvas.width / this.waveformData.length

      ctx.clearRect(0, 0, canvas.width, canvas.height)
      ctx.strokeStyle = '#ddd'
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(0, centerY)
      ctx.lineTo(canvas.width, centerY)
      ctx.stroke()

      ctx.fillStyle = '#007bff'
      this.waveformData.forEach((amplitude, index) => {
        if (amplitude > 0.001) {
          const x = index * barWidth
          const barHeight = amplitude * (centerY - 2)
          ctx.fillRect(x, centerY - barHeight, barWidth - 1, barHeight)
          ctx.fillRect(x, centerY, barWidth - 1, barHeight)
        }
      })

      if (this.currentProgress > 0) this.drawPlayhead()
    }

    drawPlayhead() {
      const { canvas, ctx } = this
      const progressX = Math.max(0, Math.min(this.currentProgress * canvas.width, canvas.width))
      ctx.save()
      ctx.strokeStyle = '#ff6b6b'
      ctx.lineWidth = 3
      ctx.lineCap = 'round'
      ctx.beginPath()
      ctx.moveTo(progressX, 0)
      ctx.lineTo(progressX, canvas.height)
      ctx.stroke()
      ctx.restore()
    }

    updateProgress(currentTime, duration) {
      if (!this.isLoaded || !duration) return
      this.currentProgress = currentTime / duration
      if (!this.currentProgress && currentTime > 0) this.currentProgress = 0.0001
      this.draw()
    }

    resetProgress() {
      this.currentProgress = 0
      this.draw()
    }
  }

  class WaveformManager {
    constructor(domCache, uiUpdater) {
      this.dom = domCache;
      this.ui = uiUpdater;
    }

    createWaveform(audioElement, playButton, audioAlreadyPlayed = false, onLoadedCallback = null) {
      if (!audioElement) return null;
      const waveformCanvas = this.dom.get('WAVEFORM_CANVAS');
      if (!waveformCanvas) return null;

      waveformCanvas.getContext('2d').clearRect(0, 0, waveformCanvas.width, waveformCanvas.height);

      const waveform = new SimpleWaveform(audioElement, waveformCanvas);

      waveform.onLoaded = () => {
        if (playButton && !audioAlreadyPlayed) this.ui.enablePlayButton(playButton);
        if (onLoadedCallback) onLoadedCallback(waveform);
      };

      if (waveform.isLoaded && playButton) {
        if (!audioAlreadyPlayed) this.ui.enablePlayButton(playButton);
        else this.ui.disablePlayButton(playButton, 'audio has already been played');
      }

      return waveform;
    }

    destroyWaveform(waveform) {
      if (waveform && waveform.destroy) waveform.destroy();
    }

    resetProgress(waveform) {
      if (waveform && waveform.resetProgress) waveform.resetProgress();
    }
  }

  window.ReviewModules.WaveformManager = WaveformManager;
})();
