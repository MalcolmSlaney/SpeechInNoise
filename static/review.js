if (typeof AudioPrefetch === 'undefined') {
  throw new Error('AudioPrefetch class is not available. Make sure audio.js loads before review.js');
}

class ReviewAudio extends AudioPrefetch {
  constructor(project) {
    super("#playing", project)
    this._startCalled = false
    this._initialized = false
    this._initialLoad = false
    this.project = project

    this.dom = new window.ReviewModules.DOMCache();
    this.state = new window.ReviewModules.StateManager();
    this.ui = new window.ReviewModules.UIUpdater(this.dom);
    this.audioManager = new window.ReviewModules.AudioManager(this.dom, this.ui);
    this.waveformManager = new window.ReviewModules.WaveformManager(this.dom, this.ui);
    this.annotationManager = new window.ReviewModules.AnnotationManager(this.dom);
    this.apiClient = new window.ReviewModules.APIClient(this.dom);
    this.audioPrefetcher = new window.ReviewModules.AudioPrefetcher();
    this.exitManager = new window.ReviewModules.ExitManager(this.dom, this.apiClient);
    this.thankYouPage = new window.ReviewModules.ThankYouPage(this.dom);
    this.audioEventHandler = new window.ReviewModules.AudioEventHandler(
      this.dom, this.ui, this.state, this.apiClient);
    this.resultHandler = new window.ReviewModules.ResultHandler(
      this.apiClient, this.annotationManager, this.dom);
    this.initializationManager = new window.ReviewModules.InitializationManager(
      this.dom, this.ui, this.exitManager, this.audioEventHandler);
    this.loadHandler = new window.ReviewModules.LoadHandler(
      this.dom, this.state, this.ui, this.audioManager,
      this.waveformManager, this.annotationManager, this.audioPrefetcher);

    this.exitManager.setupPrevention(() => !this._audioPlayed || this._reviewSubmitted);
    this.exitManager.setupExitButton(() => this.handleExit());
    this.exitManager.setupExitWarning();
  }

  _showExitWarning() { this.exitManager.showWarning(); }
  _hideExitWarning() { this.exitManager.hideWarning(); }

  async handleExit() {
    this._hideExitWarning()
    if (this._audioPlayed && !this._reviewSubmitted) {
      const nextButton = this.ui.getNextButton();
      if (nextButton && !nextButton.disabled) {
        // Review complete — submit then show thank-you
        this._exiting = true;
        try {
          await this.result(0);
        } catch (error) {
          this._exiting = false;
          alert('Error submitting review. Please try again.');
        }
      } else {
        this._showExitWarning()
      }
    } else {
      this.exitSession()
    }
  }

  async exitSession() {
    try {
      await fetch('/jnd/api/review/reset', { method: 'POST' })
    } catch (_) { /* still proceed to thank-you */ }
    const username = this._currentUsername
      || document.getElementById('username-text')?.textContent
      || 'Reviewer'
    this.showThankYouPage({ name: username })
  }

  async _trackAudioPlayed(fileId) {
    if (!fileId) return
    try {
      await fetch(`/jnd/api/review/track-played?file_id=${fileId}`, { method: 'POST' })
    } catch (_) { /* don't block user if tracking fails */ }
  }

  // Override public() — no encryption needed for review
  public() {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({ kty: "RSA", n: "dummy", e: "AQAB" })
    })
  }

  autostart() {
    return !this._exiting;
  }

  loaded() {
    if (this._exiting) {
      if (this.ready) this.ready()
      return;
    }
    if (this.autostart && this.autostart()) {
      super.loaded()
    } else {
      if (this.ready) this.ready()
    }
  }

  prefetch(next) {
    const filtered = {};
    // 'cur' holds the new file URL; use it as key 0 for the parent's prefetch
    if (next.cur && typeof next.cur === 'string' && next.cur !== '') {
      filtered[0] = next.cur;
    } else if (next[0] && typeof next[0] === 'string' && next[0] !== '') {
      filtered[0] = next[0];
    }
    for (const key in next) {
      const numKey = parseInt(key);
      if (!isNaN(numKey) && numKey.toString() === key) {
        const value = next[key];
        if (typeof value === 'string' && value !== '') {
          if (key !== '0' || !filtered[0]) filtered[key] = value;
        }
      }
    }
    super.prefetch(filtered);
  }

  src(url) {
    // Block src() calls while result() is in flight
    if (this._inResultCall) return;

    const strUrl = String(url || '')
    if (!strUrl || strUrl === this.project || strUrl === "#playing") return;

    const blockedPaths = ['/review', '/review/', '/jnd/api/review', '/jnd/api/review/']
    if (blockedPaths.includes(strUrl)) return;

    if (typeof url === 'string' && (url.startsWith('/') || url.startsWith('http') || url.startsWith('blob:'))) {
      const audioElement = document.getElementById('playing')
      if (audioElement) {
        audioElement.pause()
        audioElement.currentTime = 0
        if (audioElement.src && audioElement.src !== url) {
          audioElement.removeAttribute('src')
          audioElement.load()
        }
      }
      super.src(url)
    }
  }

  start(project) {
    const projectToUse = project || this.project || "review"
    if (this._startCalled === true) {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({ cur: "", name: "Unknown", answer: [""] })
      })
    }
    this._startCalled = true
    this.project = projectToUse

    return fetch(`/jnd/api/${this.project}/start`)
      .then(response => {
        if (!response.ok) {
          this._startCalled = false
          if (response.status === 400 || response.status === 401) {
            window.location.href = "/jnd/api/review/";
          }
        }
        return response
      })
      .catch(() => {
        this._startCalled = false
        return { ok: false, status: 500, json: () => Promise.resolve({ cur: "", name: "Unknown", answer: [""] }) }
      })
  }

  initialize() {
    if (this._initialized) return
    this._initialized = true
    super.initialize()
    if (!this._startCalled) this.start(this.project)
    this.initializationManager.setupButtons(this);
    this.setupAudioProgress();
  }

  _handlePlaybackButtonClick() {
    const audio = this.audioManager.getAudioElement();
    if (!audio?.src || audio.ended) return;
    if (audio.paused) {
      audio.play().then(() => {
        this.resetPlaybackButton('pause');
        this.ui.disablePlayButton(this.playbackButton, 'playback started');
      }).catch(() => {
        alert('Audio not accessible. Please try again.');
      });
    }
  }

  load(data) {
    if (this._exiting) {
      this._exiting = false;
      const username = this._currentUsername
        || document.getElementById('username-text')?.textContent
        || 'Reviewer';
      this.showThankYouPage({ name: username });
      fetch('/jnd/api/review/reset', { method: 'POST' }).catch(() => {});
      return;
    }

    if (!data.answer) data.answer = ['', ''];

    this.loadHandler.handleFileLoad(data, this).catch(() => {
      this._loadFallback(data);
    });
  }

  _loadFallback(data) {
    this._audioPlayed = data.already_played === true || data.already_played === 'true';
    this._currentFileId = data.file_id || null;
    this._reviewSubmitted = false;
    this._hideExitWarning();

    if (!data.cur) {
      this.showThankYouPage(data);
      return;
    }

    this.ui.updateHeaderFields(data);
    this.ui.updateCurrentFilename(data.cur);
    if (data.name) {
      this.ui.updateLabelerName(data.name);
      this._currentUsername = data.name;
    }

    const audioElement = this.audioManager.getAudioElement();
    this.audioManager.resetAudioElement(this.playbackButton, this._audioPlayed);
    this.audioManager.clearAnnotationUI();

    if (data.answer?.[0]) {
      this.annotationManager.createAnnotationUI(data.answer[0]);
    }

    if (audioElement && data.cur) {
      const onSrcSet = (url) => {
        this.src(url);
        this.waveformManager.destroyWaveform(this.waveform);
        this.waveform = this.waveformManager.createWaveform(audioElement, this.playbackButton, this._audioPlayed);
      };
      this.audioPrefetcher.prefetchWithFallback(data.cur, onSrcSet, onSrcSet);
    }

    this.resetAudioProgress();
    this.initializationManager._setupAnnotationListeners(this);

    setTimeout(() => {
      this.audioEventHandler._updateNextButtonState(this.nextButton, this);
    }, 200);
  }

  async result(key) {
    this._inResultCall = true;
    try {
      await this.resultHandler.submitResult(this, super.result, key);
    } finally {
      this._inResultCall = false;
    }
  }

  options(answer) {
    this.annotationManager.createAnnotationUI(answer);
  }

  aux_data() {
    return this.annotationManager.getAnnotationData();
  }

  showThankYouPage(data) {
    const audioElement = this.audioManager.getAudioElement();
    if (audioElement) {
      audioElement.pause();
      audioElement.currentTime = 0;
      audioElement.removeAttribute('src');
      audioElement.load();
    }
    this.thankYouPage.show(data);
  }

  setupAudioProgress() {
    const audioElement = this.audioManager.getAudioElement();
    if (!audioElement) return;

    const waveformCanvas = this.dom.get('WAVEFORM_CANVAS');
    if (waveformCanvas) {
      this.waveform = this.waveformManager.createWaveform(audioElement, this.playbackButton, this._audioPlayed);
    }

    const nextButton = this.ui.getNextButton();
    this.audioEventHandler.setupEventHandlers(audioElement, this.playbackButton, nextButton, this.waveform, this);
  }

  resetAudioProgress() {
    this.waveformManager.resetProgress(this.waveform);
  }

  resetPlaybackButton(...add) {
    if (this.playbackButton) this.ui.resetPlaybackButton(this.playbackButton, ...add);
  }

  enableNextButton() { this.ui.enableNextButton(); }
  disableNextButton() { this.ui.disableNextButton(); }

  formatTime(seconds) {
    if (isNaN(seconds)) return '0:00'
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }
}

let audio = new ReviewAudio("review");
