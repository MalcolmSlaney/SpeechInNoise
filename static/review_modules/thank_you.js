/**
 * Thank you page
 */

(function() {
  'use strict';
  
  const DOM_IDS = window.ReviewModules.DOM_IDS;

  class ThankYouPage {
    constructor(domCache) {
      this.dom = domCache;
    }

    /**
     * Show the thank you page.
     * @param {Object} data - Data object containing name
     */
    show(data) {
      const name = data.name || 'Reviewer';
      
      // Hide the next wrapper
      const nextWrapper = this.dom.get('NEXT_WRAPPER');
      if (nextWrapper) {
        nextWrapper.style.display = 'none';
      }

      // Show thank you message in the main content area
      const interactive = this.dom.get('INTERACTIVE');
      if (interactive) {
        interactive.innerHTML = `
          <div style="text-align: center; padding: 40px 20px; min-height: 400px; display: flex; flex-direction: column; justify-content: center; align-items: center;">
            <h2 style="color: var(--page-text-color, #000); margin-bottom: 20px; font-size: 2em;">Thank You, Reviewer ${name}!</h2>
            <p style="color: var(--page-text-color, #666); font-size: 1.2em;">You may now close this window.</p>
          </div>
        `;
      }
    }
  }

  window.ReviewModules.ThankYouPage = ThankYouPage;
})();

