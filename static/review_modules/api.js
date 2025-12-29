/* API client for submitting reviews */

(function() {
  'use strict';
  
  const API_ENDPOINTS = window.ReviewModules.API_ENDPOINTS;
  const DOM_IDS = window.ReviewModules.DOM_IDS;

  class APIClient {
    constructor(domCache) {
      this.dom = domCache;
    }

    async submitReview(project, annotations, unclear) {
      const res = JSON.stringify(annotations);
      const unclearCheckbox = this.dom.get('UNCLEAR_CHECKBOX');
      const unclearValue = unclear !== undefined ? unclear : (unclearCheckbox ? unclearCheckbox.checked : false);

      const url = API_ENDPOINTS.RESULT(project) + `?annotations=${res}&unclear=${unclearValue}`;
      console.log('Calling result API:', url);

      const response = await fetch(url, { method: 'POST' });

      if (!response.ok) {
        console.error('API request failed:', response.status, response.statusText);
        throw new Error(`API request failed: ${response.status}`);
      }

      return response;
    }

    async parseResponse(response) {
      const clonedResponse = response.clone();
      const text = await clonedResponse.text();

      let data;
      try {
        data = JSON.parse(text);
      } catch (e) {
        console.error('API returned invalid JSON:', text);
        throw new Error(`API returned invalid JSON: ${text.substring(0, 100)}`);
      }

      return data;
    }

    handleResponseError(data) {
      if (!data.error) return null;

      console.error('API returned error:', data.error);

      if (data.cur && data.cur !== '') {
        console.warn('API returned error but cur is not empty, continuing:', data.error);
        return null;
      } else {
        console.error('API error with no next file:', data.error);
        if (data.error.includes('ref=') || data.error.includes('labeler=')) {
          console.error('FK constraint details:', data.error);
        }
        return data.error;
      }
    }

    async trackAudioPlayed(fileId) {
      if (!fileId) return;

      try {
        const response = await fetch(API_ENDPOINTS.TRACK_PLAYED, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ file_id: fileId })
        });

        if (!response.ok) {
          console.warn('Failed to track audio played:', response.status);
        }
      } catch (error) {
        console.warn('Error tracking audio played:', error);
      }
    }

    async resetSession() {
      try {
        await fetch(API_ENDPOINTS.RESET, { method: 'POST' });
      } catch (error) {
        console.warn('Error resetting session:', error);
      }
    }
  }

  window.ReviewModules.APIClient = APIClient;
})();

