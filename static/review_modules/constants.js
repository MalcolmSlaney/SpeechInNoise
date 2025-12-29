/* constants for the review modules */

window.ReviewModules = window.ReviewModules || {};

window.ReviewModules.BUTTON_STATES = {
  PLAY: 'play',
  PAUSE: 'pause',
  DISABLED_OPACITY: '0.5',
  ENABLED_OPACITY: '1',
  DISABLED_CURSOR: 'not-allowed',
  ENABLED_CURSOR: 'pointer'
};

window.ReviewModules.DOM_IDS = {
  USERNAME_TEXT: 'username-text',
  FILES_REVIEWED: 'files-reviewed',
  TEST_TYPE: 'test-type',
  FILE_PROGRESS: 'file-progress',
  UNCLEAR_CHECKBOX: 'unclear-checkbox',
  PLAYBACK_BUTTON: 'playback',
  EXIT_SESSION_BUTTON: 'exit-session-btn',
  EXIT_WARNING_MESSAGE: 'exit-warning-message',
  NEXT_AUDIO_BUTTON: 'next-audio',
  AUX_DATA: 'aux-data',
  WAVEFORM_CANVAS: 'waveform-canvas',
  AUDIO_ELEMENT: 'playing',
  CURRENT_FILENAME: 'current-filename',
  LABELER_NAME: 'labeler-name',
  INTERACTIVE: 'interactive',
  NEXT_WRAPPER: 'next-wrapper',
  FOOTER: 'footer'
};

window.ReviewModules.API_ENDPOINTS = {
  RESULT: (project) => `/jnd/api/${project}/result`,
  RESET: '/jnd/api/review/reset',
  TRACK_PLAYED: '/jnd/api/review/track-played'
};

window.ReviewModules.WARNING_STYLES = {
  POSITION: 'absolute',
  BOTTOM: '90px',
  RIGHT: '15px',
  COLOR: '#dc3545',
  FONT_SIZE: '18px',
  FONT_WEIGHT: '500',
  TEXT_ALIGN: 'right',
  WHITE_SPACE: 'nowrap'
};

window.ReviewModules.WARNING_MESSAGE = 'Please submit your review before exiting.';

