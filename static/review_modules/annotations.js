/** annotation checkboxes */

(function() {
  'use strict';
  
  const DOM_IDS = window.ReviewModules.DOM_IDS;

  class AnnotationManager {
    constructor(domCache) {
      this.dom = domCache;
    }

    /**
     * Create annotation UI for word scoring using an answer (space-separated words to create checkboxes for
     */
    createAnnotationUI(answer) {
      const holder = this.dom.querySelector('#aux-data');
      if (!holder || !answer) return;

      const existing = holder.querySelector('.options-case');
      if (existing) existing.remove();

      const container = holder.appendChild(document.createElement('div'));
      container.classList.add('options-case');

      answer.split(' ').forEach((x, i) => {
        const name = `option-${i}`;
        const wrapper = container.appendChild(document.createElement('div'));

        for (const j of ['on', 'off']) {
          const check = wrapper.appendChild(document.createElement('input'));
          const label = wrapper.appendChild(document.createElement('label'));

          check.type = 'radio'; // always one or the other
          check.id = `${name}-${j}`;
          check.name = name;
          check.classList.add('annotation', `annotation-${j}`);
          check.required = true;

          label.htmlFor = `${name}-${j}`;
          label.classList.add('option', 'base-button', `option-${j}`);
          label.textContent = x;
        }
      });
    }

    /**
     * Get annotation data (which words were marked as "on").
     * @returns {Array<boolean>} Array of booleans indicating which words were marked
     */
    getAnnotationData() {
      return Array.from(document.querySelectorAll('.annotation-on')).map(x => x.checked);
    }

    /**
     * Validate annotation UI was created successfully.
     * @param {Function} callback - Optional callback to call after validation
     */
    validateAnnotationUI(callback) {
      setTimeout(() => {
        const checkboxes = document.querySelectorAll('.annotation');
        const count = checkboxes.length;
        if (count === 0) {
          console.error('No checkboxes created! options() may have failed.');
        }
        if (callback) callback(count);
      }, 100);
    }
  }

  window.ReviewModules.AnnotationManager = AnnotationManager;
})();

