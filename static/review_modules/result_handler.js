/* submit review results and load next file */

(function() {
  'use strict';

  class ResultHandler {
    constructor(apiClient, annotationManager, domCache) {
      this.api = apiClient;
      this.annotations = annotationManager;
      this.dom = domCache;
    }

    async submitResult(context, parentResult, key = 0) {
      if (context.backlogged > 0) {
        return;
      }

      context.backlogged += 1;

      try {
        const submitFunction = async (k) => {
          return await this._createSubmitFunction(context)(k);
        };

        if (parentResult) {
          await this._handleWithParent(context, parentResult, submitFunction, key);
        } else {
          await this._handleDirectSubmission(context, submitFunction, key);
        }
      } catch (error) {
        console.error('Error in result submission:', error);
        context.backlogged = 0;
        alert('Error loading next audio. Please try again.');
      }
    }

    _createSubmitFunction(context) {
      return async (k) => {
        let annotations;
        if (this.annotations) {
          annotations = this.annotations.getAnnotationData();
        } else {
          annotations = context.aux_data();
        }

        const unclearCheckbox = this.dom.get('UNCLEAR_CHECKBOX');
        const unclear = unclearCheckbox ? unclearCheckbox.checked : false;

        if (this.api) {
          const response = await this.api.submitReview(context.project, annotations, unclear);
          const data = await this.api.parseResponse(response);
          const error = this.api.handleResponseError(data);
          
          if (error && !data.cur) {
            context._lastError = error;
          }
          
          context.backlogged = 0;
          return response;
        } else {
          const res = JSON.stringify(annotations);
          const url = `/jnd/api/${context.project}/result?annotations=${res}&unclear=${unclear}`;
          const response = await fetch(url, { method: 'POST' });
          
          if (!response.ok) {
            context.backlogged = 0;
            throw new Error(`API request failed: ${response.status}`);
          }
          
          const clonedResponse = response.clone();
          const text = await clonedResponse.text();
          let data;
          try {
            data = JSON.parse(text);
          } catch (e) {
            context.backlogged = 0;
            throw new Error(`API returned invalid JSON: ${text.substring(0, 100)}`);
          }
          
          if (data.error && !data.cur) {
            context._lastError = data.error;
          }
          
          context.backlogged = 0;
          return response;
        }
      };
    }

    async _handleWithParent(context, parentResult, submitFunction, key) {
      let capturedData = null;
      let dataCapturePromise = null;

      const wrappedSubmitFunction = async (k) => {
        const response = await submitFunction(k);
        const responseClone = response.clone();
        
        try {
          capturedData = await responseClone.json();
          console.log('Captured data from API response:', capturedData);
          
          if (dataCapturePromise && dataCapturePromise.resolve) {
            dataCapturePromise.resolve(capturedData);
          }
        } catch (e) {
          console.error('Error parsing response JSON:', e);
          if (dataCapturePromise && dataCapturePromise.reject) {
            dataCapturePromise.reject(e);
          }
        }
        
        return response;
      };

      const waitForData = new Promise((resolve, reject) => {
        dataCapturePromise = { resolve, reject };
      });

      parentResult.call(context, key, wrappedSubmitFunction);

      try {
        capturedData = await waitForData;
        console.log('Data captured, calling load() with:', capturedData);
        context.load(capturedData);
      } catch (e) {
        console.error('Error waiting for data capture:', e);
        context.backlogged = 0;
      }
    }

    async _handleDirectSubmission(context, submitFunction, key) {
      const response = await submitFunction(key);
      if (response.ok) {
        const data = await response.json();
        if (data && typeof data === 'object' && (data.cur !== undefined || data.next !== undefined)) {
          context.load(data);
        } else {
          console.error('Invalid data structure from API:', data);
          context.backlogged = 0;
        }
      }
    }
  }

  window.ReviewModules.ResultHandler = ResultHandler;
})();

