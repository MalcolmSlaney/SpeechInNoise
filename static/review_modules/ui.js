/* centralized UI updates */
(function() {
  'use strict';
  
  const DOM_IDS = window.ReviewModules.DOM_IDS;
  const BUTTON_STATES = window.ReviewModules.BUTTON_STATES;

  class UIUpdater {
    constructor(domCache) {
      this.dom = domCache;
    }

    updateHeaderFields(data) {
      if (data.participant_id && data.test) {
        const name = data.name || 'Unknown Reviewer';
        const subjectName = data.username || `Subject ${data.participant_id}`;
        const reviewed = data.position || 0;

        const usernameText = this.dom.get('USERNAME_TEXT');
        const filesReviewed = this.dom.get('FILES_REVIEWED');
        const testType = this.dom.get('TEST_TYPE');
        const fileProgress = this.dom.get('FILE_PROGRESS');

        if (usernameText) usernameText.textContent = name;
        if (filesReviewed) filesReviewed.textContent = `Files Reviewed by You: ${reviewed}`;
        if (testType) testType.textContent = `Test Type: ${data.test}`;

        if (fileProgress && data.current_file_num !== undefined && data.total_files !== undefined) {
          fileProgress.textContent = `File ${data.current_file_num} of ${data.total_files}`;
        } else if (fileProgress) {
          fileProgress.textContent = '';
        }

        console.log('Subject Name:', subjectName);
        console.log('Total Reviews:', data.review_count || 0);
      } else {
        this.clearHeaderFields();
      }
    }

    clearHeaderFields() {
      const usernameText = this.dom.get('USERNAME_TEXT');
      const filesReviewed = this.dom.get('FILES_REVIEWED');
      const testType = this.dom.get('TEST_TYPE');

      if (usernameText) usernameText.textContent = '';
      if (filesReviewed) filesReviewed.textContent = '';
      if (testType) testType.textContent = '';
    }

    enablePlayButton(button) {
      if (!button) return;
      button.disabled = false;
      button.style.opacity = BUTTON_STATES.ENABLED_OPACITY;
      button.style.cursor = BUTTON_STATES.ENABLED_CURSOR;
    }

    disablePlayButton(button, reason = '') {
      if (!button) return;
      button.disabled = true;
      button.style.opacity = BUTTON_STATES.DISABLED_OPACITY;
      button.style.cursor = BUTTON_STATES.DISABLED_CURSOR;
      if (reason) {
        console.log(`Play button disabled - ${reason}`);
      }
    }

    updateCurrentFilename(filename) {
      const el = this.dom.get('CURRENT_FILENAME');
      if (el) {
        el.textContent = filename || 'No file loaded';
      }
    }

    updateLabelerName(name) {
      const el = this.dom.get('LABELER_NAME');
      if (el && name) {
        el.textContent = name;
      }
    }
  }

  window.ReviewModules.UIUpdater = UIUpdater;
})();

