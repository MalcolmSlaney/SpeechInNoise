/**
 * resetting and managing component state.
 * Simple flags on browser side
 */

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

  /**
   * Reset state for a new file.
   * @param {Object} data - Data object from API
   */
  resetForNewFile(data) {
    // Check if audio has already been played (from API response or page reload)
    const alreadyPlayed = data.already_played === true || data.already_played === 'true';

    // Reset flags for new file (unless already played)
    this._audioPlayed = alreadyPlayed;
    this._reviewSubmitted = false;
    this._currentFileId = data.file_id || null;
    this._lastError = null;
  }

  /**
   * Mark audio as played.
   */
  markAudioPlayed() {
    this._audioPlayed = true;
  }

  /**
   * Mark review as submitted.
   */
  markReviewSubmitted() {
    this._reviewSubmitted = true;
  }

  /**
   * Check if audio has been played.
   * @returns {boolean}
   */
  hasAudioPlayed() {
    return this._audioPlayed;
  }

  /**
   * Check if review has been submitted.
   * @returns {boolean}
   */
  hasReviewSubmitted() {
    return this._reviewSubmitted;
  }

  /**
   * Get current file ID.
   * @returns {number|null}
   */
  getCurrentFileId() {
    return this._currentFileId;
  }

  /**
   * Set current file ID.
   * @param {number|null} fileId
   */
  setCurrentFileId(fileId) {
    this._currentFileId = fileId;
  }

  /**
   * Get current username.
   * @returns {string|null}
   */
  getCurrentUsername() {
    return this._currentUsername;
  }

  /**
   * Set current username.
   * @param {string} username
   */
  setCurrentUsername(username) {
    this._currentUsername = username;
  }

  /**
   * Set last error.
   * @param {string|null} error
   */
  setLastError(error) {
    this._lastError = error;
  }

  /**
   * Get last error.
   * @returns {string|null}
   */
  getLastError() {
    return this._lastError;
  }

  /**
   * Clear last error.
   */
  clearLastError() {
    this._lastError = null;
  }
  }

  window.ReviewModules.StateManager = StateManager;
})();

