/* cache DOM elements */

(function() {
  'use strict';
  
  const DOM_IDS = window.ReviewModules.DOM_IDS;

  class DOMCache {
    constructor() {
      this._cache = {};
    }

    getElement(id) {
      if (!this._cache[id]) {
        this._cache[id] = document.getElementById(id);
      }
      return this._cache[id];
    }

    get(key) {
      const id = DOM_IDS[key];
      if (!id) {
        console.warn(`DOM_IDS key "${key}" not found`);
        return null;
      }
      return this.getElement(id);
    }

    clear() {
      this._cache = {};
    }

    clearElement(id) {
      delete this._cache[id];
    }

    querySelector(selector, cache = false) {
      if (cache && this._cache[selector]) {
        return this._cache[selector];
      }
      const element = document.querySelector(selector);
      if (cache && element) {
        this._cache[selector] = element;
      }
      return element;
    }

    querySelectorAll(selector) {
      return document.querySelectorAll(selector);
    }
  }

  window.ReviewModules.DOMCache = DOMCache;
})();

