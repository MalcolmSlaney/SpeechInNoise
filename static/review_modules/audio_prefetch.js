/*
* prefetch audio files, create blob urls
*/
(function() {
  'use strict';

  class AudioPrefetcher {
    constructor() {
      this._currentBlobUrl = null;
    }

    _revokeCurrentBlobUrl() {
      if (this._currentBlobUrl) {
        try {
          URL.revokeObjectURL(this._currentBlobUrl);
          console.log('Revoked previous blob URL');
        } catch (error) {
          console.warn('Error revoking blob URL:', error);
        }
        this._currentBlobUrl = null;
      }
    }

    async prefetchAudio(url) {
      try {
        const response = await fetch(url);
        if (!response.ok) {
          throw new Error(`Failed to fetch audio: ${response.status}`);
        }

        const buffer = await response.arrayBuffer();
        const blob = new Blob([buffer], { type: 'audio/wav' });
        const blobUrl = URL.createObjectURL(blob);

        this._revokeCurrentBlobUrl();
        this._currentBlobUrl = blobUrl;

        console.log('Audio prefetched, created blob URL');
        return blobUrl;
      } catch (error) {
        console.error('Error prefetching audio:', error);
        throw error;
      }
    }

    async prefetchWithFallback(url, onSuccess, onError) {
      try {
        const blobUrl = await this.prefetchAudio(url);
        onSuccess(blobUrl);
      } catch (error) {
        console.warn('Prefetch failed, using original URL:', error);
        this._revokeCurrentBlobUrl();
        if (onError) {
          onError(url);
        }
      }
    }

    cleanup() {
      this._revokeCurrentBlobUrl();
    }
  }

  window.ReviewModules.AudioPrefetcher = AudioPrefetcher;
})();

