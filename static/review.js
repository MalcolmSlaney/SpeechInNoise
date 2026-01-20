// Shared AudioContext to avoid creating multiple instances
let sharedAudioContext = null;

function getAudioContext() {
  if (!sharedAudioContext) {
    sharedAudioContext = new (window.AudioContext || window.webkitAudioContext)();
    // Handle AudioContext state changes
    sharedAudioContext.addEventListener('statechange', () => {
      if (sharedAudioContext.state === 'suspended') {
        // Try to resume if suspended
        sharedAudioContext.resume().catch(e => {
          console.warn('Could not resume AudioContext:', e);
        });
      }
    });
  }
  // Resume if suspended
  if (sharedAudioContext.state === 'suspended') {
    sharedAudioContext.resume().catch(e => {
      console.warn('Could not resume AudioContext:', e);
    });
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
    
    // Load waveform data when audio loads
    // Remove any existing listeners first to avoid duplicates
    this.audio.removeEventListener('loadeddata', this._loadWaveformHandler);
    this._loadWaveformHandler = () => this.loadWaveform();
    this.audio.addEventListener('loadeddata', this._loadWaveformHandler);
    
    // Draw empty waveform initially
    this.drawEmpty()
  }
  
  // Cleanup method to properly destroy the waveform
  destroy() {
    // Abort any ongoing fetch
    if (this._loadWaveformAbortController) {
      this._loadWaveformAbortController.abort();
      this._loadWaveformAbortController = null;
    }
    // Remove event listener
    if (this._loadWaveformHandler) {
      this.audio.removeEventListener('loadeddata', this._loadWaveformHandler);
      this._loadWaveformHandler = null;
    }
    // Clear canvas
    if (this.ctx) {
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    }
  }
  
  async loadWaveform() {
    // Abort any previous load attempt
    if (this._loadWaveformAbortController) {
      this._loadWaveformAbortController.abort();
    }
    this._loadWaveformAbortController = new AbortController();
    
    try {
      // Use shared AudioContext instead of creating a new one
      const audioContext = getAudioContext();
      
      // Load the actual audio file as an ArrayBuffer
      const response = await fetch(this.audio.src, { 
        signal: this._loadWaveformAbortController.signal 
      });
      const arrayBuffer = await response.arrayBuffer();
      
      // Decode the audio data
      const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
      
      // Extract waveform data from the actual audio buffer
      this.waveformData = this.extractWaveformFromBuffer(audioBuffer);
      this.isLoaded = true;
      
      // Draw waveform
      this.draw();
      
      // Notify that waveform has loaded
      if (this.onLoaded) {
        this.onLoaded();
      }
      
    } catch (error) {
      if (error.name === 'AbortError') {
        return;
      }
      // Create fakey data if Web Audio API fails so as not to distract user
      this.waveformData = this.createDummyData();
      this.isLoaded = true;
      this.draw();
      
      // Notify that waveform has loaded 
      if (this.onLoaded) {
        this.onLoaded();
      }
    } finally {
      this._loadWaveformAbortController = null;
    }
  }
  
  extractWaveformFromBuffer(audioBuffer) {
    const waveform = []
    const targetBars = 200
    const channelData = audioBuffer.getChannelData(0) // Get first channel
    const samplesPerBar = Math.floor(channelData.length / targetBars)
    
    for (let i = 0; i < targetBars; i++) {
      const startSample = i * samplesPerBar
      const endSample = Math.min(startSample + samplesPerBar, channelData.length)
      
      let sum = 0
      let maxAmplitude = 0
      let sampleCount = 0
      
      // Analyze this chunk of samples
      for (let j = startSample; j < endSample; j++) {
        const sample = channelData[j]
        sum += Math.abs(sample)
        maxAmplitude = Math.max(maxAmplitude, Math.abs(sample))
        sampleCount++
      }
      
      // Calculate RMS (Root Mean Square) for this chunk
      const rms = Math.sqrt(sum / sampleCount)
      
      // Apply mathematical weighting to accentuate quiet parts
      let weightedAmplitude = rms
      
      // Apply logarithmic scaling to accentuate
      if (rms > 0.001) { // Only apply scaling to non-silent areas
        weightedAmplitude = Math.pow(rms, 0.6) // Compress high values
      } else {
        weightedAmplitude = 0 // Force silence to be exactly 0
      }
      
      // Apply additional silence emphasis
      if (rms < 0.005) {
        weightedAmplitude = 0 // Very quiet = silence
      }
      
      waveform.push(weightedAmplitude)
    }
    
    return waveform
  }
  
  createDummyData() {
    // Create dummy waveform data with clear silences
    const dummy = []
    for (let i = 0; i < 200; i++) {
      if (i < 30 || i > 170) {
        // Silence at beginning and end
        dummy.push(0)
      } else if (i > 80 && i < 90) {
        // Silence in middle
        dummy.push(0)
      } else if (i > 120 && i < 130) {
        // Another silence
        dummy.push(0)
      } else {
        // Audio with varying amplitude
        const baseAmplitude = Math.sin(i * 0.05) * 0.3 + Math.random() * 0.2
        dummy.push(Math.max(0, baseAmplitude))
      }
    }
    return dummy
  }
  
  drawEmpty() {
    const canvas = this.canvas
    const ctx = this.ctx
    const width = canvas.width
    const height = canvas.height
    const centerY = height / 2
    
    // Clear canvas
    ctx.clearRect(0, 0, width, height)
    
    // Draw center line
    ctx.strokeStyle = '#ddd'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(0, centerY)
    ctx.lineTo(width, centerY)
    ctx.stroke()
    
    // Draw placeholder text
    ctx.fillStyle = '#999'
    ctx.font = '12px Arial'
    ctx.textAlign = 'center'
    ctx.fillText('Waveform will appear when audio loads', width / 2, centerY)
  }
  
  draw() {
    if (!this.isLoaded || !this.waveformData.length) return
    
    const canvas = this.canvas
    const ctx = this.ctx
    const width = canvas.width
    const height = canvas.height
    const centerY = height / 2
    const barWidth = width / this.waveformData.length
    
    // Clear canvas
    ctx.clearRect(0, 0, width, height)
    
    // Draw center line
    ctx.strokeStyle = '#ddd'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(0, centerY)
    ctx.lineTo(width, centerY)
    ctx.stroke()
    
    // Draw waveform bars
    ctx.fillStyle = '#007bff'
    
    this.waveformData.forEach((amplitude, index) => {
      const x = index * barWidth
      const barHeight = amplitude * (centerY - 2)
      
      // Only draw bars if there's actual amplitude (not silence)
      if (amplitude > 0.001) {
        // Draw both positive and negative bars for symmetry
        ctx.fillRect(x, centerY - barHeight, barWidth - 1, barHeight)
        ctx.fillRect(x, centerY, barWidth - 1, barHeight)
      }
      // Silences (amplitude near 0) are left as empty space, showing the center line
    })
    
    if (this.currentProgress > 0) {
      this.drawPlayhead()
    }
  }
  
  drawPlayhead() {
    const canvas = this.canvas
    const ctx = this.ctx
    const width = canvas.width
    const height = canvas.height
    const progressX = Math.max(0, Math.min(this.currentProgress * width, width))
    
    ctx.save()
    ctx.strokeStyle = '#ff6b6b'
    ctx.lineWidth = 3
    ctx.lineCap = 'round'
    ctx.beginPath()
    ctx.moveTo(progressX, 0)
    ctx.lineTo(progressX, height)
    ctx.stroke()
    ctx.restore()
  }
  
  updateProgress(currentTime, duration) {
    if (!this.isLoaded) return
    if (!duration || duration === 0) return
    
    this.currentProgress = currentTime / duration
    if (this.currentProgress === 0 && currentTime > 0) {
      this.currentProgress = 0.0001
    }
    this.draw()
  }
  
  resetProgress() {
    this.currentProgress = 0
    this.draw() // Redraw without playhead
  }
}

// ReviewAudio extends AudioPrefetch directly (like Audio in record.js)
// provides prefetching and audio loading functionality
if (typeof AudioPrefetch === 'undefined') {
  throw new Error('AudioPrefetch class is not available. Make sure audio.js loads before review.js');
}

class ReviewAudio extends AudioPrefetch {
  constructor(project) {
    // Pass "#playing" as the audio selector, and project as the second argument
    // matches Audio class in record.js: super("#playing", project)
    super("#playing", project)
    // Initialize flags after super() - parent may have called start() already
    if (this._startCalled === undefined) {
      this._startCalled = false
    }
    this._initialized = false
    this._initialLoad = true
    this.project = project
    
    // Initialize refactored modules (if available)
    if (window.ReviewModules) {
      this.dom = new window.ReviewModules.DOMCache();
      this.state = new window.ReviewModules.StateManager();
      this.ui = new window.ReviewModules.UIUpdater(this.dom);
      this.audioManager = new window.ReviewModules.AudioManager(this.dom, this.ui);
      this.waveformManager = new window.ReviewModules.WaveformManager(
        this.dom, 
        SimpleWaveform, 
        this.ui
      );
      this.annotationManager = new window.ReviewModules.AnnotationManager(this.dom);
      this.apiClient = new window.ReviewModules.APIClient(this.dom);
      this.audioPrefetcher = new window.ReviewModules.AudioPrefetcher();
      this.exitManager = new window.ReviewModules.ExitManager(this.dom, this.apiClient);
      this.buttonManager = this.ui; // ButtonManager consolidated into UIUpdater
      this.navigationManager = this.exitManager; // NavigationManager consolidated into ExitManager
      this.thankYouPage = new window.ReviewModules.ThankYouPage(this.dom);
      this.audioEventHandler = new window.ReviewModules.AudioEventHandler(
        this.dom,
        this.ui,
        this.state,
        this.apiClient
      );
      this.resultHandler = new window.ReviewModules.ResultHandler(
        this.apiClient,
        this.annotationManager,
        this.dom
      );
      this.initializationManager = new window.ReviewModules.InitializationManager(
        this.dom,
        this.buttonManager,
        this.exitManager,
        this.audioEventHandler
      );
      this.loadHandler = new window.ReviewModules.LoadHandler(
        this.dom,
        this.state,
        this.ui,
        this.audioManager,
        this.waveformManager,
        this.annotationManager,
        this.audioPrefetcher
      );
    }
    
    // Setup navigation prevention
    if (this.navigationManager) {
      this.navigationManager.setupPrevention(() => {
        return !this._audioPlayed || this._reviewSubmitted;
      });
    } else {
      this._setupNavigationPrevention();
    }
    
    // Setup exit button and warning
    if (this.exitManager) {
      this.exitManager.setupExitButton(() => this.handleExit());
      this.exitManager.setupExitWarning();
    } else {
      this._setupExitButton();
      this._setupExitWarning();
    }
  }
  
  _setupExitButton() {
    const exitBtn = this.dom ? this.dom.get('EXIT_SESSION_BUTTON') : document.getElementById('exit-session-btn');
    if (exitBtn && !exitBtn.hasAttribute('data-listener-attached')) {
      exitBtn.addEventListener('click', () => {
        this.handleExit();
      });
      exitBtn.setAttribute('data-listener-attached', 'true');
    } else if (!exitBtn) {
      // Button not found yet, try again after a short delay
      setTimeout(() => this._setupExitButton(), 100);
    }
  }
  
  _setupExitWarning() {
    // Create warning message element if it doesn't exist
    const exitBtn = this.dom ? this.dom.get('EXIT_SESSION_BUTTON') : document.getElementById('exit-session-btn');
    if (exitBtn) {
      // Check if warning element already exists
      let warningEl = this.dom ? this.dom.get('EXIT_WARNING_MESSAGE') : document.getElementById('exit-warning-message');
      if (!warningEl) {
        warningEl = document.createElement('div');
        warningEl.id = window.ReviewModules?.DOM_IDS?.EXIT_WARNING_MESSAGE || 'exit-warning-message';
        
        // Use constants if available
        const styles = window.ReviewModules?.WARNING_STYLES;
        if (styles) {
          warningEl.style.cssText = `position: ${styles.POSITION}; bottom: ${styles.BOTTOM}; right: ${styles.RIGHT}; color: ${styles.COLOR}; font-size: ${styles.FONT_SIZE}; font-weight: ${styles.FONT_WEIGHT}; display: none; text-align: ${styles.TEXT_ALIGN}; white-space: ${styles.WHITE_SPACE};`;
        } else {
          warningEl.style.cssText = 'position: absolute; bottom: 90px; right: 15px; color: #dc3545; font-size: 18px; font-weight: 500; display: none; text-align: right; white-space: nowrap;';
        }
        
        warningEl.textContent = window.ReviewModules?.WARNING_MESSAGE || 'Please fill out your review before exiting.';
        exitBtn.parentElement.appendChild(warningEl);
      }
    } else {
      // Button not found yet, try again after a short delay
      setTimeout(() => this._setupExitWarning(), 100);
    }
  }
  
  _showExitWarning() {
    if (this.exitManager) {
      this.exitManager.showWarning();
    } else {
      const warningEl = document.getElementById('exit-warning-message');
      if (warningEl) {
        warningEl.style.display = 'block';
      }
    }
  }
  
  _hideExitWarning() {
    if (this.exitManager) {
      this.exitManager.hideWarning();
    } else {
      const warningEl = document.getElementById('exit-warning-message');
      if (warningEl) {
        warningEl.style.display = 'none';
      }
    }
  }
  
  async handleExit() {
    // Hide any previous warning
    this._hideExitWarning()
    
    // Check if audio has been played
    if (this._audioPlayed && !this._reviewSubmitted) {
      // Check if the review is complete by checking if Next Audio button is enabled
      let nextButton;
      if (this.buttonManager) {
        nextButton = this.buttonManager.getNextButton();
      } else {
        nextButton = this.nextButton || document.getElementById('next-audio');
      }
      const isReviewComplete = nextButton && !nextButton.disabled;
      
      if (isReviewComplete) {
        // Review is complete - submit it and then exit
        // Set flag to prevent loading next audio - load() will show thank you page
        this._exiting = true;
        try {
          await this.result(0);
        } catch (error) {
          this._exiting = false;
          alert('Error submitting review. Please try again.');
        }
      } else {
        // Review is not complete - show warning message
        this._showExitWarning()
        // Don't allow exit
        return
      }
    } else {
      // Audio hasn't been played or review has been submitted - allow exit
      this.exitSession()
    }
  }
  
  async exitSession() {
    try {
      // Call review_reset endpoint to clear session
      const response = await fetch('/jnd/api/review/reset', { method: 'POST' })
      
      // Get username for thank you page (use stored username or get from DOM)
      const username = this._currentUsername || (document.getElementById('username-text')?.textContent) || 'Reviewer'
      
      // Show thank you page instead of redirecting
      this.showThankYouPage({ name: username })
    } catch (error) {
      // Still show thank you page even if reset fails
      const username = this._currentUsername || (document.getElementById('username-text')?.textContent) || 'Reviewer'
      this.showThankYouPage({ name: username })
    }
  }
  
  async _trackAudioPlayed(fileId) {
    // Track that audio has been played in the database
    if (!fileId) return
    
    try {
      const response = await fetch(`/jnd/api/review/track-played?file_id=${fileId}`, {
        method: 'POST'
      })
      if (!response.ok) {
        // Tracking failed, but don't block user
      }
    } catch (error) {
      // Don't block user if tracking fails
    }
  }

  _setupNavigationPrevention() {
    // Prevent navigation only if audio has been played but review not submitted
    this._beforeUnloadHandler = (e) => {
      if (this._audioPlayed && !this._reviewSubmitted) {
        // Modern browsers ignore custom messages, but we still trigger the dialog
        e.preventDefault()
        e.returnValue = 'You have played audio but haven\'t submitted your review yet. Are you sure you want to leave?'
        return e.returnValue
      }
    }
    window.addEventListener('beforeunload', this._beforeUnloadHandler)
    
    // Prevent back button navigation if audio played but review not submitted
    this._popStateHandler = (e) => {
      if (this._audioPlayed && !this._reviewSubmitted) {
        // Push current state back to prevent navigation
        history.pushState(null, '', window.location.href)
        // Show warning
        if (confirm('You have played audio but haven\'t submitted your review yet. Are you sure you want to leave? You will need to submit your review next time, but you won\t be able to replay the audio.')) {
          // Reset flags to allow navigation
          this._audioPlayed = false
          this._reviewSubmitted = false
          // Remove listeners to allow navigation
          window.removeEventListener('beforeunload', this._beforeUnloadHandler)
          window.removeEventListener('popstate', this._popStateHandler)
          history.back()
        }
      }
    }
    window.addEventListener('popstate', this._popStateHandler)
    
    history.pushState(null, '', window.location.href)
  }
  
  allowExit() {
    this._audioPlayed = false
    this._reviewSubmitted = false
    window.removeEventListener('beforeunload', this._beforeUnloadHandler)
    window.removeEventListener('popstate', this._popStateHandler)
  }

  // Override public() to prevent parent from making incorrect API calls
  public() {
    // Return a Response-like object with a dummy key since we don't need encryption for review
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({
        kty: "RSA",
        n: "dummy",
        e: "AQAB"
      })
    })
  }

  autostart() { 
    return false; 
  }
  
  // Override loaded() to prevent autoplay
  loaded() {
    if (this.autostart && this.autostart()) {
      // Only autoplay if autostart() returns true
      super.loaded()
    } else {
      // Don't autoplay - just mark as ready
      if (this.ready) {
        this.ready()
      }
    }
  }

  prefetch(next) {
    // Filter to only include URL-related fields
    // The parent's prefetch() iterates over all keys and tries to fetch string values
    const filtered = {};
 
    // The parent result() does Object.assign(data, {0: oldUrl})
    // which means key 0 has the old URL, but 'cur' has the new URL from the API.
    // We use 'cur' as the new file URL, not key 0.
    if (next.cur && typeof next.cur === 'string' && next.cur !== '') {
      // The new URL is in 'cur', use it as key 0 (this is the file we want to play next)
      filtered[0] = next.cur;
    } else if (next[0] && typeof next[0] === 'string' && next[0] !== '') {
      // Fallback: if 'cur' doesn't exist, use key 0 (but this might be the old URL)
      filtered[0] = next[0];
    }

    for (const key in next) {
      const numKey = parseInt(key);
      // Only keep numeric keys (0, 1, 2, etc.) - these contain actual URLs
      //No 'next' (it's an object), 'cur' (handled above), or other fields
      if (!isNaN(numKey) && numKey.toString() === key) {
        // Only include if it's a string URL (not an object or empty)
        const value = next[key];
        if (typeof value === 'string' && value !== '') {
          // Don't overwrite key 0 if already set it from 'cur'
          if (key !== '0' || !filtered[0]) {
            filtered[key] = value;
          }
        }
      }
    }
    
    // Call parent's prefetch with filtered data (only numeric keys with URL strings)
    super.prefetch(filtered);
  }

  // Override src() to validate URLs and prevent setting invalid sources
  src(url) {
    const strUrl = String(url || '')
    
    // Block empty strings, project name, or "#playing" selector
    if (!strUrl || strUrl === "" || strUrl === this.project || strUrl === "#playing") {
      return
    }
    
    // Block exact invalid paths (but allow valid file path /jnd/api/review/upload/...)
    const blockedPaths = [
      `/review`,
      `/review/`,
      `/jnd/api/review`,
      `/jnd/api/review/`,
    ]
    
    if (blockedPaths.includes(strUrl)) {
      return
    }
    
    // Only set src if it looks like a valid URL (starts with / or http or blob:)
    if (typeof url === 'string' && (url.startsWith('/') || url.startsWith('http') || url.startsWith('blob:'))) {
      // Stop and reset the audio element before setting new src
      // This ensures the old audio stops playing when we load a new file
      const audioElement = document.getElementById('playing')
      if (audioElement) {
        // Stop current playback
        audioElement.pause()
        audioElement.currentTime = 0
        // If changing to a different URL, stop the old one first
        const currentSrc = audioElement.src
        if (currentSrc && currentSrc !== url && currentSrc !== '') {
          // Clear the src temporarily to stop the old audio
          audioElement.removeAttribute('src')
          audioElement.load() // This stops the current audio and resets the element
        }
      }
      
      super.src(url)
    }
  }

  start(project) {
    // Handle case where project is passed as argument or use instance property
    const projectToUse = project || this.project || "review"
    
    // Check if already called - use strict equality to handle undefined
    if (this._startCalled === true) {
      // Return a Response-like object that the parent's promise chain expects
      // Prevent parent from trying to load data again
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({cur: "", name: "Unknown", answer: [""]})
      })
    }
    
    // Mark as called before making the request
    this._startCalled = true
    this.project = projectToUse
    
    const url = `/jnd/api/${this.project}/start`
    
    // Return the fetch Response directly so the parent's promise chain can process it
    // The parent will call .json() on the response and then call load()
    // also handle when the parent load() might not work correctly
    return fetch(url)
      .then(response => {
        if (!response.ok) {
          this._startCalled = false
        }
        // Return the response object so parent can process it
        // The parent will call response.json() and then load() with the data
        return response
      })
      .catch((error) => { 
        this._startCalled = false
        // Return an error response object
        return {
          ok: false,
          status: 500,
          json: () => Promise.resolve({cur: "", name: "Unknown", answer: [""]})
        }
      })
  }

  initialize() {
    if (this._initialized) {
      return
    }
    this._initialized = true
    
    super.initialize()
    
    // Auto-start review on page load - no subject selection needed
    // Only call start() if it hasn't been called already 
    this._initialLoad = false // Allow auto-start
    if (!this._startCalled) {
      this.start(this.project)
    }
    
    // Setup buttons using InitializationManager if available
    if (this.initializationManager) {
      this.initializationManager.setupButtons(this);
    } else {
      // Fallback: setup buttons manually
      if (!this.nextButton) {
        this.nextButton = document.getElementById('next-audio');
      }
      this.playbackButton = document.getElementById('playback');
      if (this.playbackButton && !this.playbackButton.hasAttribute('data-listener-attached')) {
        this.resetPlaybackButton('play');
        this.playbackButton.addEventListener('click', () => {
          this._handlePlaybackButtonClick();
        });
        this.playbackButton.setAttribute('data-listener-attached', 'true');
      }
      if (this.nextButton && !this.nextButton.hasAttribute('data-listener-attached')) {
        this.nextButton.addEventListener('click', () => {
          this._reviewSubmitted = true;
          this._hideExitWarning();
          this.result(0);
        });
        this.nextButton.setAttribute('data-listener-attached', 'true');
      }
    }
    
    // Set up audio progress tracking
    this.setupAudioProgress();
    
    // Set up exit button (already done in constructor, but ensure here)
    if (!this.exitManager) {
      this._setupExitButton();
    }
  }
  
  _handlePlaybackButtonClick() {
    const audio = this.audioManager ? this.audioManager.getAudioElement() : document.getElementById('playing');
    if (!audio?.src) return;
    
    // Users can only play once - if audio has ended, prevent replay
    if (audio.ended) {
      return;
    }
    
    // Users cannot pause - only play
    if (audio.paused) {
      audio.play().then(() => {
        this.resetPlaybackButton('pause');
        if (this.ui && this.playbackButton) {
          this.ui.disablePlayButton(this.playbackButton, 'playback started');
        } else if (this.playbackButton) {
          this.playbackButton.disabled = true;
        }
      }).catch((error) => {
        alert('Audio not accessible. Please try again.');
      });
    }
  }

  load(data) {
    // If we're exiting, skip loading the next audio and go straight to thank you page
    if (this._exiting) {
      this._exiting = false; // Reset flag
      const username = this._currentUsername || (document.getElementById('username-text')?.textContent) || 'Reviewer';
      this.showThankYouPage({ name: username });
      return;
    }
    
    // Ensure answer is valid
    if (!data.answer) {
      console.warn('No answer in data, setting default empty array');
      data.answer = ['', ''];
    }
    
    // Use LoadHandler if available, otherwise fallback to direct implementation
    if (this.loadHandler) {
      this.loadHandler.handleFileLoad(data, this).catch(error => {
        // Fallback if loadHandler fails
        this._loadFallback(data);
      });
    } else {
      this._loadFallback(data);
    }
    
    // Don't call parent load() - it might interfere with audio source setting
  }
  
  _loadFallback(data) {
    const alreadyPlayed = data.already_played === true || data.already_played === 'true';
    this._audioPlayed = alreadyPlayed;
    this._currentFileId = data.file_id || null;
    this._reviewSubmitted = false;
    this._hideExitWarning();
    
    if (!data.cur || data.cur === '') {
      this.showThankYouPage(data);
      return;
    }
    
    if (this.ui) {
      this.ui.updateHeaderFields(data);
      this.ui.updateCurrentFilename(data.cur);
      if (data.name) {
        this.ui.updateLabelerName(data.name);
        this._currentUsername = data.name;
      }
    }
    
    const audioElement = this.audioManager ? this.audioManager.getAudioElement() : document.getElementById('playing');
    if (audioElement && this.audioManager) {
      this.audioManager.resetAudioElement(this.playbackButton, this._audioPlayed);
      this.audioManager.clearAnnotationUI();
    }
    
    if (data.answer && data.answer[0] && this.annotationManager) {
      this.annotationManager.createAnnotationUI(data.answer[0]);
    } else if (data.answer && data.answer[0]) {
      this.options(data.answer[0]);
    }
    
    if (audioElement && data.cur) {
      if (this.audioPrefetcher) {
        this.audioPrefetcher.prefetchWithFallback(
          data.cur,
          (blobUrl) => {
            this.src(blobUrl);
            if (this.waveformManager) {
              this.waveformManager.destroyWaveform(this.waveform);
              this.waveform = this.waveformManager.createWaveform(audioElement, this.playbackButton, this._audioPlayed);
            }
          },
          (url) => {
            this.src(url);
            if (this.waveformManager) {
              this.waveformManager.destroyWaveform(this.waveform);
              this.waveform = this.waveformManager.createWaveform(audioElement, this.playbackButton, this._audioPlayed);
            }
          }
        );
      } else {
        // Fallback: set audio source directly if prefetcher is not available
        this.src(data.cur);
        if (this.waveformManager && audioElement) {
          this.waveformManager.destroyWaveform(this.waveform);
          this.waveform = this.waveformManager.createWaveform(audioElement, this.playbackButton, this._audioPlayed);
        }
      }
    }
    
    this.resetAudioProgress();
    
    // Ensure annotation listeners are set up (if page was reloaded)
    if (this.initializationManager) {
      this.initializationManager._setupAnnotationListeners(this);
    }
    
    if (this.audioEventHandler && this.nextButton) {
      // Wait for annotations to be created, then check button state
      setTimeout(() => {
        this.audioEventHandler._updateNextButtonState(this.nextButton, this);
      }, 200);
    } else if (this.nextButton) {
      // disable button if we can't check state
      this.disableNextButton();
    }
  }

  async result(key, f=undefined) {
    if (this.resultHandler) {
      await this.resultHandler.submitResult(this, super.result, key);
    } else {
      await this._resultFallback(key);
    }
  }
  
  async _resultFallback(key) {
    if (this.backlogged > 0) return;
    this.backlogged += 1;
    
    try {
      const annotations = this.aux_data();
      const unclearCheckbox = document.getElementById('unclear-checkbox');
      const unclear = unclearCheckbox ? unclearCheckbox.checked : false;
      const res = JSON.stringify(annotations);
      const url = `/jnd/api/${this.project}/result?annotations=${res}&unclear=${unclear}`;
      
      const response = await fetch(url, { method: 'POST' });
      if (!response.ok) {
        this.backlogged = 0;
        throw new Error(`API request failed: ${response.status}`);
      }
      
      const data = await response.json();
      if (data && typeof data === 'object' && (data.cur !== undefined || data.next !== undefined)) {
        this.load(data);
      } else {
        this.backlogged = 0;
      }
    } catch (error) {
      this.backlogged = 0;
      alert('Error loading next audio. Please try again.');
    }
  }

  // Create annotation UI for word scoring
  options(answer) {
    if (this.annotationManager) {
      this.annotationManager.createAnnotationUI(answer);
    } else {
      // Fallback implementation
      const holder = document.querySelector("#aux-data");
      if (!holder || !answer) return;
      const existing = holder.querySelector(".options-case");
      if (existing) existing.remove();
      const container = holder.appendChild(document.createElement("div"));
      container.classList.add("options-case");
      answer.split(" ").forEach((x, i) => {
        const name = `option-${i}`;
        const wrapper = container.appendChild(document.createElement("div"));
        for (const j of ['on', 'off']) {
          const check = wrapper.appendChild(document.createElement("input"));
          const label = wrapper.appendChild(document.createElement("label"));
          check.type = "radio";
          check.id = `${name}-${j}`;
          check.name = name;
          check.classList.add("annotation", `annotation-${j}`);
          check.required = true;
          label.htmlFor = `${name}-${j}`;
          label.classList.add("option", "base-button", `option-${j}`);
          label.textContent = x;
        }
      });
    }
  }

  aux_data() {
    return Array.from(document.querySelectorAll(".annotation-on")).map(
      x => x.checked)
  }


  showThankYouPage(data) {
    if (this.thankYouPage) {
      this.thankYouPage.show(data);
    } else {
      // Fallback implementation
      const interactive = document.getElementById('interactive');
      const nextWrapper = document.getElementById('next-wrapper');
      if (interactive) interactive.style.display = 'none';
      if (nextWrapper) nextWrapper.style.display = 'none';
      
      const footer = document.getElementById('footer');
      if (footer) {
        const name = data.name || 'Reviewer';
        footer.innerHTML = `
          <div style="text-align: center; padding: 20px;">
            <h2 style="color: #28a745; margin-bottom: 20px;">Thank You, ${name}!</h2>
          </div>
        `;
      }
    }
  }

  setupAudioProgress() {
    const audioElement = this.audioManager ? this.audioManager.getAudioElement() : document.getElementById('playing');
    if (!audioElement) return;
    
    // Initialize waveform using WaveformManager if available
    if (this.waveformManager) {
      const waveformCanvas = this.dom.get('WAVEFORM_CANVAS');
      if (waveformCanvas) {
        this.waveform = this.waveformManager.createWaveform(
          audioElement,
          this.playbackButton,
          this._audioPlayed
        );
      }
    } else {
      // Fallback to direct creation
      const waveformCanvas = document.getElementById('waveform-canvas');
      if (waveformCanvas) {
        this.waveform = new SimpleWaveform(audioElement, waveformCanvas);
        this.waveform.onLoaded = () => {
          if (this.playbackButton && !this._audioPlayed) {
            this.ui?.enablePlayButton(this.playbackButton);
          }
        };
        if (this.waveform.isLoaded && this.playbackButton && !this._audioPlayed) {
          this.ui?.enablePlayButton(this.playbackButton);
        }
      }
    }
    
    // Setup event handlers using AudioEventHandler if available
    if (this.audioEventHandler) {
      const nextButton = this.buttonManager ? this.buttonManager.getNextButton() : document.getElementById('next-audio');
      this.audioEventHandler.setupEventHandlers(
        audioElement,
        this.playbackButton,
        nextButton,
        this.waveform,
        this
      );
    } else {
      // Fallback
      this._setupAudioEventHandlersFallback(audioElement);
    }
  }
  
  _setupAudioEventHandlersFallback(audioElement) {
    audioElement.addEventListener('play', () => {
      this._audioPlayed = true;
      this.disableNextButton();
      if (this.playbackButton) {
        this.resetPlaybackButton('pause');
      }
      if (this._currentFileId) {
        this._trackAudioPlayed(this._currentFileId);
      }
    });
    
    audioElement.addEventListener('ended', () => {
      this.enableNextButton();
      if (this.playbackButton) {
        this.playbackButton.disabled = true;
        this.resetPlaybackButton('play');
        this.playbackButton.style.opacity = '0.5';
        this.playbackButton.style.cursor = 'not-allowed';
      }
    });
    
    audioElement.addEventListener('timeupdate', () => {
      if (audioElement.duration && this.waveform) {
        this.waveform.updateProgress(audioElement.currentTime, audioElement.duration);
      }
    });
    
    audioElement.addEventListener('pause', (e) => {
      if (!audioElement.ended) {
        audioElement.play();
      } else {
        this.enableNextButton();
        if (this.playbackButton) {
          this.resetPlaybackButton('play');
        }
      }
    });
  }

  resetAudioProgress() {
    // Reset waveform progress using WaveformManager if available
    if (this.waveformManager) {
      this.waveformManager.resetProgress(this.waveform);
    } else if (this.waveform) {
      this.waveform.resetProgress();
    }
  }

  resetPlaybackButton(...add) {
    if (this.buttonManager && this.playbackButton) {
      this.buttonManager.resetPlaybackButton(this.playbackButton, ...add);
    } else if (this.playbackButton) {
      // Fallback 
      const playbackButtonClasses = ['play', 'playable', 'pause', 'load', 'stop', 'record', 'done', 'error', 'ing'];
      for (const className of playbackButtonClasses) {
        this.playbackButton.classList.remove(className);
      }
      for (const className of add) {
        this.playbackButton.classList.add(className);
      }
    }
  }

  enableNextButton() {
    if (this.buttonManager) {
      this.buttonManager.enableNextButton();
    } else {
      const nextButton = document.getElementById('next-audio');
      if (nextButton) {
        nextButton.disabled = false;
        nextButton.style.opacity = '1';
      }
    }
  }

  disableNextButton() {
    if (this.buttonManager) {
      this.buttonManager.disableNextButton();
    } else {
      const nextButton = document.getElementById('next-audio');
      if (nextButton) {
        nextButton.disabled = true;
        nextButton.style.opacity = '0.5';
      }
    }
  }

  formatTime(seconds) {
    if (isNaN(seconds)) return '0:00'
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

}

// Add global error handlers
window.addEventListener('error', (event) => {
});

window.addEventListener('unhandledrejection', (event) => {
  // Unhandled promise rejection 
});

// Create ReviewAudio instance
let audio = new ReviewAudio("review");
