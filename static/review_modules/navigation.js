/* handle browser navigation when review is in progress */

(function() {
  'use strict';

  class NavigationManager {
    constructor() {
      this._preventExit = false;
      this._historyState = null;
    }

    setupPrevention(checkCanExit) {
      if (history.state === null) {
        history.pushState({ preventBack: true }, '', location.href);
      }

      window.addEventListener('popstate', (event) => {
        if (event.state && event.state.preventBack) {
          history.pushState({ preventBack: true }, '', location.href);
          console.log('Back navigation prevented');
        }
      });

      window.addEventListener('beforeunload', (event) => {
        if (checkCanExit && !checkCanExit()) {
          event.preventDefault();
          event.returnValue = '';
          return '';
        }
      });
    }

    allowExit() {
      this._preventExit = false;
      history.replaceState(null, '', location.href);
    }

    preventExit() {
      this._preventExit = true;
    }

    isExitPrevented() {
      return this._preventExit;
    }
  }

  window.ReviewModules.NavigationManager = NavigationManager;
})();

