/* resetting and managing component state */

(function() {
  'use strict';

  class StateManager {
  constructor() {
    this._audioPlayed = false;
    this._reviewSubmitted = false;
    this._currentFileId = null;
    this._currentUsername = null;
    this._lastError = null;
  }

  resetForNewFile(data) {
    const alreadyPlayed = data.already_played === true || data.already_played === 'true';
    this._audioPlayed = alreadyPlayed;
    this._reviewSubmitted = false;
    this._currentFileId = data.file_id || null;
    this._lastError = null;
  }

  markAudioPlayed() {
    this._audioPlayed = true;
  }

  markReviewSubmitted() {
    this._reviewSubmitted = true;
  }

  hasAudioPlayed() {
    return this._audioPlayed;
  }

  hasReviewSubmitted() {
    return this._reviewSubmitted;
  }

  getCurrentFileId() {
    return this._currentFileId;
  }

  setCurrentFileId(fileId) {
    this._currentFileId = fileId;
  }

  getCurrentUsername() {
    return this._currentUsername;
  }

  setCurrentUsername(username) {
    this._currentUsername = username;
  }

  setLastError(error) {
    this._lastError = error;
  }

  getLastError() {
    return this._lastError;
  }

  clearLastError() {
    this._lastError = null;
  }
  }

  window.ReviewModules.StateManager = StateManager;
})();

