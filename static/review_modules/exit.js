/* exit session and warnings to prevent incomplete reviews */

(function() {
  'use strict';
  
  const DOM_IDS = window.ReviewModules.DOM_IDS;
  const WARNING_STYLES = window.ReviewModules.WARNING_STYLES;
  const WARNING_MESSAGE = window.ReviewModules.WARNING_MESSAGE;

  class ExitManager {
    constructor(domCache, apiClient) {
      this.dom = domCache;
      this.api = apiClient;
    }

    setupExitButton(handleExit) {
      const exitBtn = this.dom.get('EXIT_SESSION_BUTTON');
      if (exitBtn && !exitBtn.hasAttribute('data-listener-attached')) {
        exitBtn.addEventListener('click', () => {
          handleExit();
        });
        exitBtn.setAttribute('data-listener-attached', 'true');
      } else if (!exitBtn) {
        setTimeout(() => this.setupExitButton(handleExit), 100);
      }
    }

    setupExitWarning() {
      const exitBtn = this.dom.get('EXIT_SESSION_BUTTON');
      if (exitBtn) {
        let warningEl = this.dom.get('EXIT_WARNING_MESSAGE');
        if (!warningEl) {
          warningEl = document.createElement('div');
          warningEl.id = DOM_IDS.EXIT_WARNING_MESSAGE;

          if (WARNING_STYLES) {
            warningEl.style.cssText = `position: ${WARNING_STYLES.POSITION}; bottom: ${WARNING_STYLES.BOTTOM}; right: ${WARNING_STYLES.RIGHT}; color: ${WARNING_STYLES.COLOR}; font-size: ${WARNING_STYLES.FONT_SIZE}; font-weight: ${WARNING_STYLES.FONT_WEIGHT}; display: none; text-align: ${WARNING_STYLES.TEXT_ALIGN}; white-space: ${WARNING_STYLES.WHITE_SPACE};`;
          } else {
            warningEl.style.cssText = 'position: absolute; bottom: 90px; right: 15px; color: #dc3545; font-size: 18px; font-weight: 500; display: none; text-align: right; white-space: nowrap;';
          }

          warningEl.textContent = WARNING_MESSAGE || 'Please submit your review before exiting.';
          exitBtn.parentElement.appendChild(warningEl);
        }
      } else {
        setTimeout(() => this.setupExitWarning(), 100);
      }
    }

    showWarning() {
      const warningEl = this.dom.get('EXIT_WARNING_MESSAGE');
      if (warningEl) {
        warningEl.style.display = 'block';
      }
    }

    hideWarning() {
      const warningEl = this.dom.get('EXIT_WARNING_MESSAGE');
      if (warningEl) {
        warningEl.style.display = 'none';
      }
    }
  }

  window.ReviewModules.ExitManager = ExitManager;
})();

