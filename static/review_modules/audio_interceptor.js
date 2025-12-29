/**
 * Prevents invalid URLs from being set on the audio element's src property.
 */

(function() {
  'use strict';
  
  const DOM_IDS = window.ReviewModules.DOM_IDS;

  class AudioSrcInterceptor {
    constructor() {
      this._intercepted = false;
      this._observer = null;
    }

    /**
     * Setup the audio src interceptor.
     */
    setup() {
      // Try immediately
      this._trySetup();

      // Also try after delays to catch late assignments
      setTimeout(() => this._trySetup(), 100);
      setTimeout(() => this._trySetup(), 500);

      // Setup MutationObserver
      this._setupMutationObserver();
    }

    /**
     * Try to setup the interceptor.
     * @private
     */
    _trySetup() {
      const audioElement = document.getElementById(DOM_IDS.AUDIO_ELEMENT);
      if (!audioElement) {
        return;
      }

      if (audioElement.hasAttribute('data-src-intercepted')) {
        return; // Already intercepted
      }

      audioElement.setAttribute('data-src-intercepted', 'true');
      let currentSrc = audioElement.src || '';
      const interceptor = this; // Capture interceptor instance

      Object.defineProperty(audioElement, 'src', {
        get: function() {
          return currentSrc;
        },
        set: function(value) {
          const strValue = String(value);
          
          // Block invalid URLs
          if (interceptor._isInvalidUrl(strValue)) {
            console.warn('Blocked invalid audio src assignment:', value);
            console.trace('Stack trace:');
            return;
          }

          // Only allow valid URL formats
          if (interceptor._isValidUrlFormat(strValue)) {
            console.log('Setting valid audio src:', strValue);
            currentSrc = strValue;
            // Call original setter with audioElement as 'this'
            Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'src').set.call(audioElement, strValue);
          } else {
            console.warn('Blocked invalid audio src format:', value);
          }
        },
        configurable: true
      });

      this._intercepted = true;
    }

    /**
     * Check if URL is invalid.
     * @private
     */
    _isInvalidUrl(strValue) {
      const invalidUrls = [
        '', 'review', '/review', '/review/', 
        'https://quicksin.stanford.edu/review/'
      ];
      
      return !strValue || 
             invalidUrls.includes(strValue) || 
             strValue.endsWith('/review/');
    }

    /**
     * Check if URL has valid format.
     * @private
     */
    _isValidUrlFormat(strValue) {
      if (!strValue.startsWith('/') && 
          !strValue.startsWith('http') && 
          !strValue.startsWith('blob:')) {
        return false;
      }

      // Additional check: must not be just "/review" or end with "/review/"
      return strValue !== '/review' && 
             strValue !== '/review/' && 
             !strValue.endsWith('/review/');
    }

    /**
     * Setup MutationObserver to catch src attribute changes.
     * @private
     */
    _setupMutationObserver() {
      this._observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
          if (mutation.type === 'attributes' && mutation.attributeName === 'src') {
            const audioElement = mutation.target;
            const srcValue = audioElement.getAttribute('src');
            
            if (srcValue && this._isInvalidUrl(srcValue)) {
              console.warn('MutationObserver: Blocked invalid src attribute:', srcValue);
              audioElement.removeAttribute('src');
            }
          }
        });
      });

      this._startObserving();
    }

    /**
     * Start observing the audio element.
     * @private
     */
    _startObserving() {
      const audioElement = document.getElementById(DOM_IDS.AUDIO_ELEMENT);
      if (audioElement && this._observer) {
        this._observer.observe(audioElement, { 
          attributes: true, 
          attributeFilter: ['src'] 
        });
        console.log('MutationObserver started for audio element');
      }
    }
  }

  // Auto-setup when module loads
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      const interceptor = new AudioSrcInterceptor();
      interceptor.setup();
    });
  } else {
    const interceptor = new AudioSrcInterceptor();
    interceptor.setup();
  }

  window.ReviewModules.AudioSrcInterceptor = AudioSrcInterceptor;
})();

