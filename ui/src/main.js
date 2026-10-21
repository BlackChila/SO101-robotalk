import './theme.css';
import './style.css';
import { createSpeechMeter, startSpeechLevelPump } from './speech-envelope.js';
import './shared-controls.css';
import './conversation-redesign.css';
import { preloadRealtimeMolmo } from './realtime-molmo-preload.js';
import { waitForRealtimeChannel } from './realtime-connection.js';
import { RealtimeTaskFeedback, SPOKEN_BREVITY } from './realtime-task-feedback.js';
import { conversationLanguage as normalizeConversationLanguage, languageInstruction } from './conversation-language.js';
import { sceneMessages } from './realtime-scene.js';
import { RealtimeWebSearch } from './realtime-web-search.js';
import { molmoRunStopState, keepMolmoForConversation } from './molmo-run-stop.js';
import { FaceTrackingControls } from './face-tracking.js';
import { LocalRobotConversation, piperVoiceLanguage } from './local-robot-conversation.js';
import { Insta360Controls } from './insta360-controls.js';
import { CameraSettingsToggle, CameraBrightnessControls } from './camera-settings.js';
import { VoicePicker } from './voice-picker.js';
import { SpeechWaveform } from './speech-waveform.js';

const app = document.querySelector('#app');
const cameraGear = `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true"><path d="m9 3-.6 2.4-2 .9L4.2 5.6 2 9.4l1.8 1.7v1.8L2 14.6l2.2 3.8 2.2-.7 2 .9L9 21h6l.6-2.4 2-.9 2.2.7 2.2-3.8-1.8-1.7v-1.8L22 9.4l-2.2-3.8-2.2.7-2-.9L15 3Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.5"/></svg>`;
function brightnessMarkup(index) {
  return `<div id="camera-brightness-${index}" class="camera-brightness">
    <label for="camera-brightness-input-${index}"><span>Helligkeit</span><output for="camera-brightness-input-${index}">—</output></label>
    <input id="camera-brightness-input-${index}" type="range" min="0" max="1" step="1" value="0" disabled />
    <div class="insta360-controls__actions">
      <button type="button" data-brightness-apply disabled>Helligkeit übernehmen</button>
      <button type="button" data-brightness-reset disabled>Standardhelligkeit</button>
    </div>
    <p data-brightness-message role="status">Helligkeit der Kamera manuell einstellen.</p>
  </div>`;
}

function exposureMarkup(index) {
  return `<div id="camera-exposure-${index}" class="camera-brightness" hidden>
    <label for="camera-exposure-input-${index}"><span>Belichtung</span><output for="camera-exposure-input-${index}">—</output></label>
    <input id="camera-exposure-input-${index}" type="range" min="0" max="1" step="1" value="0" disabled />
    <div class="insta360-controls__actions">
      <button type="button" data-exposure-apply disabled>Belichtung übernehmen</button>
      <button type="button" data-exposure-reset disabled>Standardbelichtung</button>
    </div>
    <p data-exposure-message role="status">Belichtung der Kamera manuell einstellen.</p>
  </div>`;
}

app.innerHTML = `
  <main class="shell">
    <header class="app-header">
      <div class="app-brand"><strong>SO-101</strong><span>Dein Roboter. Ganz nah.</span></div>
      <div class="system-status" aria-live="polite">
        <span class="system-status__item" id="asr-status"><span class="status-dot"></span><span>ASR wird geprüft</span></span>
        <span class="system-status__item" id="robot-status"><span class="status-dot"></span><span>Roboterstatus wird geprüft</span></span>
        <span class="system-status__item system-status__item--muted" id="voice-status"><span class="status-dot"></span><span>Stimme wird geprüft</span></span>
      </div>
      <button type="button" id="conversation-settings-toggle" class="conversation-settings-toggle"
          aria-label="Gesprächseinstellungen" title="Gesprächseinstellungen"
          aria-controls="conversation-settings" aria-expanded="false">${cameraGear}</button>
    </header>

    <section id="conversation-view" class="conversation-view" aria-label="Gespräch">
      <div class="conversation-main">
      <section class="conversation-stage" aria-label="Sprachgespräch">
      <div class="conversation-identity">
      <h1 id="conversation-title">Gespräch mit <span class="conversation-voice-picker">
        <select id="conversation-speaker" class="conversation-speaker" aria-label="Stimme auswählen"></select>
      </span></h1>
      </div>
      <div class="conversation-session">
      <div id="conversation-orb" class="conversation-orb" data-state="idle" aria-hidden="true">
        <div class="conversation-orb__halo"></div>
        <div class="conversation-orb__core"></div>
        <div class="conversation-bars">${[12, 18, 27, 16, 33, 24, 40, 22, 14, 31, 46, 25, 18, 38, 54, 28, 17, 36, 22, 42, 62, 35, 20, 47, 74, 44, 24, 38, 58, 31, 19, 45, 28, 16, 35, 49, 26, 14, 32, 42, 23, 16, 29, 37, 21, 14, 26, 18, 12].map(height => `<span style="--bar-height:${height}%"></span>`).join('')}</div>
      </div>
      <div class="conversation-controls">
        <button type="button" id="conversation-call" class="conversation-call" disabled>
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" aria-hidden="true"><rect x="9" y="2.5" width="6" height="12" rx="3" stroke="currentColor" stroke-width="1.8"/><path d="M5.5 10.5v1a6.5 6.5 0 0 0 13 0v-1M12 18v3.5M8.5 21.5h7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
          <span>Gespräch starten</span>
        </button>

      </div>
      <p id="conversation-feedback" class="conversation-feedback" role="status" aria-live="polite">Modelle werden geprüft …</p>
      </div>
      <div class="conversation-task-status"><span>Auftragsstatus</span>
      <p id="conversation-task-feedback" class="conversation-feedback" role="status" aria-live="polite" hidden></p>
      <span class="conversation-task-empty">—</span></div>
      </section>
      <section id="conversation-cameras" class="conversation-cameras" aria-labelledby="conversation-cameras-heading" hidden>
        <h2 id="conversation-cameras-heading">Aktuelle Kamerabilder</h2>
        <p id="conversation-camera-status" class="conversation-camera-status" role="status">Kameras werden geladen …</p>
        <div class="conversation-media">
          <div id="conversation-camera-status-host">      <div class="camera-status-row">
        <p id="camera-status" class="model-choice__camera" role="status">Kameras werden vorbereitet …</p>
        <button id="camera-reload" type="button" aria-label="Kameras neu laden" title="Kameras neu laden" disabled>
          <svg viewBox="0 0 24 24" width="19" height="19" fill="none" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.3 6.7M20 4v7h-7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
      </div>
</div>
          <div id="conversation-camera-host">      <div id="live-camera-panel">
      <div class="camera-views" aria-label="Aktuelle Kamerabilder">
        <figure><figcaption id="camera-label-1" class="conversation-camera-label">Overhead-Kamera</figcaption><span class="camera-frame"><img id="camera-view-1" alt="Overhead-Kamera" /><button id="camera-settings-toggle-1" class="camera-settings-toggle" type="button" aria-label="Einstellungen für Kamera 1" title="Kameraeinstellungen" aria-controls="camera-settings-1" aria-expanded="false" hidden>${cameraGear}</button></span></figure>
        <figure><figcaption id="camera-label-2" class="conversation-camera-label">Zweite Kamera</figcaption><span class="camera-frame"><img id="camera-view-2" alt="Zweite Kamera" /><button id="camera-settings-toggle-2" class="camera-settings-toggle" type="button" aria-label="Einstellungen für Kamera 2" title="Kameraeinstellungen" aria-controls="camera-settings-2" aria-expanded="false" hidden>${cameraGear}</button></span></figure>
        <figure id="camera-observer-view" hidden><figcaption class="conversation-camera-label">Wrist-Kamera</figcaption><span class="camera-frame"><img id="camera-view-3" alt="Wrist-Kamera" /><span id="face-tracking" class="face-tracking" hidden><img data-face-image alt="Aufrechtes Wrist-Livebild mit Tracking-Markierung" hidden /></span><button id="camera-settings-toggle-3" class="camera-settings-toggle" type="button" aria-label="Einstellungen für Wrist-Kamera" title="Kameraeinstellungen" aria-controls="camera-settings-3" aria-expanded="false" hidden>${cameraGear}</button></span></figure>
      </div>
      <div class="camera-adjustments">
      <section id="camera-settings-1" class="insta360-controls camera-settings" aria-labelledby="camera-settings-heading-1" hidden>
        <h2 id="camera-settings-heading-1">Kamera 1 · Einstellungen</h2>
        ${exposureMarkup(1)}
        ${brightnessMarkup(1)}
      </section>
      <section id="camera-settings-2" class="insta360-controls camera-settings" aria-labelledby="camera-settings-heading-2" hidden>
        <h2 id="camera-settings-heading-2">Kamera 2 · Einstellungen</h2>
        ${exposureMarkup(2)}
        ${brightnessMarkup(2)}
      <section id="insta360-controls" class="insta360-controls" aria-labelledby="insta360-heading" hidden>
        <h2 id="insta360-heading">Insta360 · Ausschnitt ausrichten</h2>
        <div class="insta360-controls__sliders">
          <label for="insta360-yaw"><span>Horizontal</span><output for="insta360-yaw" data-value="yaw">65°</output>
            <input id="insta360-yaw" data-axis="yaw" type="range" min="-180" max="180" step="0.5" value="65" />
          </label>
          <label for="insta360-pitch"><span>Vertikal / Neigung</span><output for="insta360-pitch" data-value="pitch">15°</output>
            <input id="insta360-pitch" data-axis="pitch" type="range" min="-90" max="90" step="0.5" value="15" />
          </label>
          <label for="insta360-roll"><span>Drehung</span><output for="insta360-roll" data-value="roll">55°</output>
            <input id="insta360-roll" data-axis="roll" type="range" min="-180" max="180" step="0.5" value="55" />
          </label>
          <label for="insta360-zoom"><span>Nähe / Zoom</span><output for="insta360-zoom" data-value="zoom">1×</output>
            <input id="insta360-zoom" data-axis="zoom" type="range" min="1" max="2" step="0.05" value="1" />
          </label>
        </div>
        <p>Der Zoom verengt den sichtbaren Ausschnitt. Die Ausgabe bleibt 960 × 720 (4:3).</p>
        <div class="insta360-controls__actions">
          <button type="button" data-apply disabled>Ausschnitt übernehmen</button>
          <button type="button" data-reset>Standardwerte</button>
        </div>
        <p data-message role="status">Ausrichtung und Zoom einstellen; anschließend übernehmen.</p>
      </section>
      </section>
      <section id="camera-settings-3" class="insta360-controls camera-settings" aria-labelledby="camera-settings-heading-3" hidden>
        <h2 id="camera-settings-heading-3">Wrist-Kamera · Einstellungen</h2>
        ${exposureMarkup(3)}
        ${brightnessMarkup(3)}
      </section>
      </div></div>
</div>
        </div>
      </section>
      </div>
      <section id="conversation-settings" class="conversation-settings" aria-labelledby="conversation-settings-heading" hidden>
        <header class="conversation-settings-header"><h2 id="conversation-settings-heading">Gesprächseinstellungen</h2><button id="conversation-settings-close" type="button" aria-label="Gesprächseinstellungen schließen"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true"><path d="m6 15 6-6 6 6" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></button></header>
      <fieldset class="conversation-mode" id="conversation-mode">
        <legend>Sprachmodus</legend>
        <label><input type="radio" name="conversation-mode" value="realtime" checked><span>ChatGPT Realtime</span></label>
        <label><input type="radio" name="conversation-mode" value="local"><span>Lokal · Qwen</span></label>
        <label><input type="radio" name="conversation-mode" value="piper"><span>Lokal · Piper</span></label>
      </fieldset>
      <fieldset class="conversation-mode conversation-language" id="conversation-language">
        <legend>Gesprächssprache</legend>
        <label><input type="radio" name="conversation-language" value="German" checked><span>Deutsch</span></label>
        <label><input type="radio" name="conversation-language" value="English"><span>English</span></label>
        <p>Gilt ab dem nächsten Gespräch, einschließlich der Begrüßung.</p>
      </fieldset>
        <section class="conversation-setting-group">
        <div class="section-heading"><h3>Suchstart</h3><span class="help-tip">
          <button class="help-tip__trigger" type="button" aria-label="Hinweis zum Suchstart" aria-describedby="conversation-search-help" aria-expanded="false">i</button>
          <span id="conversation-search-help" class="help-tip__popover" role="tooltip">Bestimmt die erste Suchrichtung der Basis beim nächsten Gesichtstracking-Start. Klicken auf „Suchstart“ wechselt zwischen rechts und links.</span>
        </span></div>
        <button type="button" id="face-search-direction" class="reset-button"
          aria-description="Bestimmt die erste Suchrichtung der Basis beim nächsten Gesichtstracking-Start. Klicken wechselt zwischen rechts und links.">Suchstart: rechts →</button>
        <p>Startrichtung der Basis beim nächsten Tracking-Start. Tracking startet nach dem Intro automatisch, sobald Realtime verbunden ist.</p>
        </section>
        <section class="conversation-setting-group">
        <div class="section-heading"><h3>Roboter</h3><span class="help-tip">
          <button class="help-tip__trigger" type="button" aria-label="Hinweis zur Robotersteuerung" aria-describedby="conversation-robot-help" aria-expanded="false">i</button>
          <span id="conversation-robot-help" class="help-tip__popover" role="tooltip"><strong>Roboter zurücksetzen:</strong> Stoppt den Auftrag und fährt zur Endposition des Intros, ohne Intro oder Begrüßung zu wiederholen. Das Gespräch bleibt verbunden.<br><br><strong>Model Run stoppen:</strong> Stoppt den laufenden Roboterauftrag und hält die gemessene Position. Modell und Gespräch bleiben aktiv.<br><br><strong>Modell entladen:</strong> Gibt den Speicher des Robotikmodells frei. Gespräch und Kameras bleiben aktiv. Laufende Aufträge zuerst stoppen.<br><br><strong>Torque an:</strong> Aktiviert das Drehmoment und hält die aktuelle Position.<br><br><strong>Torque Aus:</strong> Deaktiviert das Drehmoment. Der Arm wird nicht mehr aktiv gehalten.</span>
        </span></div>
        <button type="button" id="conversation-start-without-intro" class="reset-button" aria-describedby="conversation-reset-description" disabled>Roboter zurücksetzen</button>
        <p id="conversation-reset-description" class="conversation-sr-only">Stoppt den aktuellen Auftrag und fährt direkt zur Endposition des Intros, ohne Intro oder Begrüßung. Das Gespräch bleibt verbunden.</p>
        <div class="conversation-run-actions">
          <button type="button" id="conversation-task-stop" class="task-stop" disabled
            aria-description="Fordert den Stopp des laufenden Roboterauftrags an. Modell bleibt geladen und Gespräch bleibt verbunden; der Controller hält anschließend die gemessene Position.">Model Run stoppen</button>
          <div id="conversation-model-unload-host">          <button id="model-unload" type="button" hidden
            aria-description="Entlädt das Robotikmodell und gibt dessen Speicher frei. Gespräch und Kameras bleiben aktiv; laufende Aufträge zuerst stoppen.">Modell entladen</button></div>
        </div>
        <div id="conversation-torque-host"><div id="torque-actions" class="torque__actions">
        <button id="torque-on-button" class="reset-button torque-button" type="button" disabled
          aria-description="Schaltet das Motordrehmoment ein, damit der Arm seine aktuelle Position hält.">Torque an</button>
        <button id="torque-off-button" class="reset-button torque-button" type="button" disabled
          aria-description="Schaltet das Motordrehmoment aus. Der Arm wird danach nicht mehr aktiv gehalten.">Torque Aus</button>
      </div></div>
        <p id="conversation-torque-feedback" class="conversation-torque-feedback" role="status" aria-live="polite" hidden></p>
        <div class="conversation-teleop">
          <h4>Teleoperation</h4>
          <div id="conversation-teleop-host"><div id="teleop-controls">
      <div class="teleop__actions">
        <button id="teleop-start-button" class="reset-button" type="button" aria-label="Teleoperation starten" disabled>Starten</button>
        <button id="teleop-stop-button" class="reset-button" type="button" aria-label="Teleoperation stoppen" disabled>Stoppen</button>
      </div>
      <p id="teleop-status" class="teleop__status" role="status" aria-live="polite">Teleoperation wird geprüft …</p>
      </div></div>
        </div>
        </section>

      </section>
    </section>
  </main>
`;

const helpTips = [...document.querySelectorAll('.help-tip')];
function closeHelpTips(except = null) {
  helpTips.forEach((tip) => {
    if (tip === except) return;
    tip.classList.remove('is-open');
    const trigger = tip.querySelector('.help-tip__trigger');
    trigger.setAttribute('aria-expanded', 'false');
  });
}
helpTips.forEach((tip) => {
  const trigger = tip.querySelector('.help-tip__trigger');
  trigger.addEventListener('click', () => {
    const shouldOpen = !tip.classList.contains('is-open');
    closeHelpTips(tip);
    tip.classList.toggle('is-open', shouldOpen);
    trigger.setAttribute('aria-expanded', String(shouldOpen));
  });
});
document.addEventListener('pointerdown', (event) => {
  if (!event.target.closest('.help-tip')) closeHelpTips();
});
document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  closeHelpTips();
  if (document.activeElement?.classList.contains('help-tip__trigger')) document.activeElement.blur();
});

const asrStatus = document.querySelector('#asr-status');
const robotStatus = document.querySelector('#robot-status');
const torqueOnButton = document.querySelector('#torque-on-button');
const torqueOffButton = document.querySelector('#torque-off-button');
const conversationTorqueFeedback = document.querySelector('#conversation-torque-feedback');
const teleopStartButton = document.querySelector('#teleop-start-button');
const teleopStopButton = document.querySelector('#teleop-stop-button');
const teleopStatus = document.querySelector('#teleop-status');
const cameraStatus = document.querySelector('#camera-status');
const cameraReload = document.querySelector('#camera-reload');
const cameraImages = [1, 2, 3].map(index => document.querySelector(`#camera-view-${index}`));
const cameraViews = document.querySelector('.camera-views');
const wristObserverFigure = document.querySelector('#camera-observer-view');
const modelUnload = document.querySelector('#model-unload');

let status = { asrReady: false, asrLoading: false, robotConnected: false, modelSession: null, cameraModel: null, resetAvailable: false, resetRunning: false, resetHolding: false, returnAvailable: false, returnRunning: false, returnMessage: '', physicalReady: false, torqueAction: 'off', torqueAvailable: false, torqueRunning: false, torqueHolding: false, torqueMessage: '', teleoperation: { state: 'idle', occupied: false, available: false, blocker: '', message: 'Teleoperation im Backend noch nicht verfügbar.' }, taskRun: null, message: '' };
let backendReady = false;
let phase = 'idle';
let teleopActionGeneration = 0;
let cameraReady = false;
let cameraPreviewModelId = null;
let wristObserverReady = false;
let cameraFrameReady = [false, false];
let cameraOpening = false;
let cameraGeneration = 0;
const insta360Controls = new Insta360Controls(document.querySelector('#insta360-controls'), applyInsta360View);
const cameraSettings = [1, 2, 3].map((index) => new CameraSettingsToggle(
  document.querySelector(`#camera-settings-toggle-${index}`), document.querySelector(`#camera-settings-${index}`), render));
const brightnessControls = [1, 2, 3].map((index) => new CameraBrightnessControls(
  document.querySelector(`#camera-brightness-${index}`), applyCameraBrightness));
const exposureControls = [1, 2, 3].map((index) => new CameraBrightnessControls(
  document.querySelector(`#camera-exposure-${index}`), applyCameraExposure, 'exposure'));
const liveCameraPanel = document.querySelector('#live-camera-panel');
const conversationCamerasSection = document.querySelector('#conversation-cameras');
const conversationCameraStatus = document.querySelector('#conversation-camera-status');
const conversationSettings = new CameraSettingsToggle(
  document.querySelector('#conversation-settings-toggle'), document.querySelector('#conversation-settings'), () => {
    render();
    if (conversationSettings.open) void refreshStatus().then(refreshVisibleCameraPreview);
  });
document.querySelector('#conversation-settings-close').addEventListener('click', () => {
  if (!conversationSettings.open) return;
  conversationSettings.button.click();
  conversationSettings.button.focus();
});

function currentCameraModel() {
  return status.cameraModel;
}

function renderConversationSettings() {
  conversationSettings.render(true);
  conversationSettings.button.hidden = activeView !== 'conversation';
  const inConversation = activeView === 'conversation';
  conversationCamerasSection.hidden = !inConversation || !conversationSettings.open;
  renderWristObserver();
  if (inConversation && !status.cameraModel && cameraOpening) {
    conversationCameraStatus.textContent = 'Kameras werden geladen …';
  } else if (inConversation && cameraPreviewModelId !== status.cameraModel) {
    conversationCameraStatus.textContent = 'Aktuelle Kamerabilder werden geladen …';
  }
}

const activeView = 'conversation';
let modelManuallyUnloaded = sessionStorage.getItem('so101-model-manually-unloaded') === '1';
let conversationActive = false;
let conversationPhase = 'idle';
let conversationRecorder = null;
let localTaskNotice = false;
let conversationSpeechDetected = false;
let conversationStream = null;
let conversationChunks = [];
let conversationTimer = null;
let conversationAudioContext = null;
let conversationAnalyser = null;
let conversationMeter = null;
let conversationRequest = null;
let conversationGeneration = 0;
let conversationAudio = null;
let conversationMotionId = null;
let conversationIntroCompletedId = null;
let conversationVoiceOnly = false;
let conversationRecoveredId = null;
let conversationHeartbeat = null;
let conversationStopping = Promise.resolve();
let conversationRestartPending = false;
let conversationRestartCancelled = false;
let conversationResetEpoch = 0;
let conversationReturning = false;
let conversationReturnCancel = null;
let conversationEntryReady = false;
let conversationEntryPending = false;
let conversationRecoverySupported = true;
const conversationModeInputs = [...document.querySelectorAll('input[name="conversation-mode"]')];
const savedConversationMode = localStorage.getItem('so101-conversation-mode');
let conversationMode = ['local', 'piper'].includes(savedConversationMode) ? savedConversationMode : 'realtime';
const conversationLanguageInputs = [...document.querySelectorAll('input[name="conversation-language"]')];
let conversationLanguage = normalizeConversationLanguage(localStorage.getItem('so101-conversation-language'));
document.querySelector(`input[name="conversation-language"][value="${conversationLanguage}"]`).checked = true;
document.querySelector(`input[name="conversation-mode"][value="${conversationMode}"]`).checked = true;
let realtimePeer = null;
let realtimeChannel = null;
let realtimeSpeechMeter = null;
let realtimeAudioElement = null;
let realtimeLevelTimer = null;
let realtimeSpeaking = false;
const realtimeTaskCalls = new Set();
let realtimeTaskActive = false;
let realtimeTaskLastState = null;
let realtimeTaskEverStarted = false;
let realtimeMolmoPreloadWarning = '';
let realtimeTaskPoll = null;
let realtimeSpeechGripperAvailable = true;
const conversationTaskStop = document.querySelector('#conversation-task-stop');
let conversationTaskStopPending = false;

function renderConversationTaskStop() {
  const control = molmoRunStopState(status.taskRun, conversationTaskStopPending);
  conversationTaskStop.disabled = control.disabled;
  conversationTaskStop.textContent = control.label;
}
const faceTracking = new FaceTrackingControls(document.querySelector('#face-tracking'), {
  directionButton: document.querySelector('#face-search-direction'),
});
const conversationFeedback = document.querySelector('#conversation-feedback');
const conversationTaskFeedback = document.querySelector('#conversation-task-feedback');
const realtimeWebSearch = new RealtimeWebSearch();
const realtimeTaskFeedback = new RealtimeTaskFeedback(sendRealtimeEvent, (message) => {
  conversationTaskFeedback.hidden = false;
  conversationTaskFeedback.textContent = message;
}, () => conversationLanguage);
const localConversation = new LocalRobotConversation({
  voice: () => conversationSpeakerValue(),
  engine: () => conversationMode === 'piper' ? 'piper' : 'qwen',
  language: () => conversationLanguage,
  speak: async (text, signal, voice) => {
    setConversationPhase('speaking', `${conversationSpeakerName()} spricht …`);
    await speakConversation(text, signal, voice);
  },
  onTool: (call, result) => {
    if (!result) {
      setConversationPhase('thinking', call.name === 'look_at_scene' ? 'Ich schaue mich um …'
        : call.name === 'get_project_info' ? 'Technische Informationen werden geladen …'
        : call.name === 'get_creator_info' ? 'Informationen zur Projektperson werden geladen …' : 'Roboterauftrag wird übermittelt …');
      if (call.name === 'reset_robot') {
        localTaskNotice = false;
        conversationRestartPending = true;
        conversationResetEpoch++;
        conversationIntroCompletedId = null;
      }
    } else {
      if (call.name === 'reset_robot') conversationRestartPending = false;
      if (result.error) {
        conversationTaskFeedback.hidden = false;
        conversationTaskFeedback.textContent = `Werkzeug fehlgeschlagen: ${result.error}`;
      } else if (call.name === 'execute_molmo_task') {
        status.taskRun = result.taskRun;
        realtimeTaskActive = true;
        realtimeTaskEverStarted = true;
        realtimeTaskLastState = result.taskRun?.state;
        conversationTaskFeedback.hidden = false;
        conversationTaskFeedback.textContent = result.status === 'updated'
          ? 'MolmoAct2 übernimmt die neue Anweisung.' : 'MolmoAct2 bereitet den Auftrag vor.';
      } else if (call.name === 'reset_robot') {
        if (result.status !== 'reset' || result.followerTorqueHolding !== true || result.controllerRestarted !== true) {
          throw new Error('Neustart des Motorcontrollers wurde nicht bestätigt.');
        }
        realtimeTaskActive = false;
        realtimeTaskEverStarted = true;
        realtimeTaskLastState = 'stopped';
        status.taskRun = null;
        realtimeSpeechGripperAvailable = result.speechGripperAvailable !== false;
        conversationIntroCompletedId = conversationMotionId;
        conversationTaskFeedback.textContent = 'Roboter zurückgesetzt · bereit für einen neuen Auftrag.';
        faceTracking.rearmAfterReset(conversationMotionId);
      }
    }
    render();
    renderConversationMode();
  },
});
const conversationCall = document.querySelector('#conversation-call');
const conversationStartWithoutIntro = document.querySelector('#conversation-start-without-intro');
const conversationTitle = document.querySelector('#conversation-title');
const conversationSpeaker = document.querySelector('#conversation-speaker');
const conversationOrb = document.querySelector('#conversation-orb');
const conversationWaveform = new SpeechWaveform(conversationOrb);
const voicePicker = new VoicePicker({
  select: conversationSpeaker,
  onSelect: index => selectConversationSpeaker(index),
});
const voiceStatus = document.querySelector('#voice-status');
localStorage.removeItem('so101-conversation-history');
const conversationSpeakers = [
  { value: 'Ryan', name: 'Ryan' }, { value: 'Aiden', name: 'Aiden' },
  { value: 'Vivian', name: 'Vivian' }, { value: 'Serena', name: 'Serena' },
  { value: 'Uncle_Fu', name: 'Uncle Fu' }, { value: 'Dylan', name: 'Dylan' },
  { value: 'Eric', name: 'Eric' }, { value: 'Ono_Anna', name: 'Ono Anna' },
  { value: 'Sohee', name: 'Sohee' },
];
const realtimeSpeakers = ['marin', 'cedar', 'alloy', 'ash', 'ballad', 'coral', 'echo', 'sage', 'shimmer', 'verse']
  .map((value) => ({ value, name: value[0].toUpperCase() + value.slice(1) }));
const piperSpeakers = [
  { value: 'Thorsten', name: 'Thorsten · DE' }, { value: 'Kerstin', name: 'Kerstin · DE' },
  { value: 'Amy', name: 'Amy · US' }, { value: 'Ryan', name: 'Ryan · US' },
  { value: 'Alan', name: 'Alan · UK' }, { value: 'Jenny', name: 'Jenny · UK' },
];
function activeConversationSpeakers() {
  return conversationMode === 'realtime' ? realtimeSpeakers
    : conversationMode === 'piper' ? piperSpeakers.filter(({ value }) => piperVoiceLanguage(value) === conversationLanguage) : conversationSpeakers;
}
function speakerStorageKey() {
  return conversationMode === 'realtime' ? 'so101-realtime-voice'
    : conversationMode === 'piper' ? `so101-piper-voice-${conversationLanguage}` : 'so101-conversation-speaker';
}
function storedSpeakerIndex() {
  const speakers = activeConversationSpeakers();
  const saved = localStorage.getItem(speakerStorageKey()) || (conversationMode === 'piper' ? localStorage.getItem('so101-piper-voice') : null);
  const index = speakers.findIndex(({ value }) => value === saved);
  return index >= 0 ? index : conversationMode === 'local'
    ? speakers.findIndex(({ value }) => value === 'Dylan') : 0;
}
let conversationSpeakerIndex = storedSpeakerIndex();
function conversationSpeakerValue() {
  return activeConversationSpeakers()[conversationSpeakerIndex].value;
}
function renderConversationSpeaker() {
  const name = conversationSpeakerName();
  conversationTitle.setAttribute('aria-label', `Gespräch mit ${name}`);
  voicePicker.render(activeConversationSpeakers(), conversationSpeakerIndex,
    conversationMode === 'realtime' && (conversationActive || conversationReturning || conversationEntryPending));
}
function renderConversationMode() {
  conversationStartWithoutIntro.disabled = !conversationEntryReady || !conversationActive || !conversationMotionId || conversationVoiceOnly || conversationRestartPending ||
    conversationReturning || conversationEntryPending ||
    (conversationActive && ['intro', 'connecting'].includes(conversationPhase));
  conversationStartWithoutIntro.textContent = conversationRestartPending
    ? 'Roboter wird zurückgesetzt …' : 'Roboter zurücksetzen';
  renderConversationTaskStop();
  const selectable = conversationMode !== 'realtime' ||
    !(conversationActive || conversationReturning || conversationEntryPending);
  conversationSpeaker.setAttribute('aria-description', selectable
    ? 'Stimme wählen oder über dem Namen scrollen zum Wechseln'
    : 'Die Realtime-Stimme bleibt während des Gesprächs fest');
  conversationSpeaker.classList.toggle('conversation-speaker--fixed', !selectable);
  voicePicker.render(activeConversationSpeakers(), conversationSpeakerIndex, !selectable);
  conversationModeInputs.forEach((input) => {
    input.disabled = conversationActive || conversationReturning || Boolean(conversationRecoveredId) || conversationEntryPending || conversationRestartPending;
  });
  conversationLanguageInputs.forEach((input) => {
    input.disabled = conversationActive || conversationReturning || Boolean(conversationRecoveredId) || conversationEntryPending || conversationRestartPending;
  });
}
function selectConversationSpeaker(index) {
  if (conversationMode === 'realtime' &&
      (conversationActive || conversationReturning || conversationEntryPending)) return;
  const speakers = activeConversationSpeakers();
  conversationSpeakerIndex = (index + speakers.length) % speakers.length;
  localStorage.setItem(speakerStorageKey(), conversationSpeakerValue());
  renderConversationSpeaker();
  if (conversationMode === 'piper' && conversationEntryReady && !conversationActive) {
    void refreshConversationStatus();
  }
}
function conversationSpeakerName() {
  return activeConversationSpeakers()[conversationSpeakerIndex].name;
}

renderConversationSpeaker();
renderConversationMode();

function setConversationPhase(next, message) {
  conversationPhase = next;
  conversationOrb.dataset.state = next;
  conversationFeedback.textContent = message;
  conversationCall.classList.toggle('is-active', conversationActive || conversationReturning || Boolean(conversationRecoveredId));
  const buttonLabel = conversationReturning ? 'Rückfahrt stoppen'
    : conversationActive || conversationRecoveredId ? 'Gespräch beenden' : 'Gespräch starten';
  conversationCall.querySelector('span').textContent = buttonLabel;
  conversationCall.setAttribute('aria-label', buttonLabel);
  renderConversationMode();
}

conversationLanguageInputs.forEach((input) => input.addEventListener('change', () => {
  if (!input.checked || conversationActive || conversationReturning || conversationRecoveredId || conversationEntryPending || conversationRestartPending) return;
  conversationLanguage = normalizeConversationLanguage(input.value);
  localStorage.setItem('so101-conversation-language', conversationLanguage);
  conversationSpeakerIndex = storedSpeakerIndex();
  renderConversationSpeaker();
  renderConversationMode();
  if (conversationEntryReady) void refreshConversationStatus();
}));

conversationModeInputs.forEach((input) => input.addEventListener('change', async () => {
  if (!input.checked || conversationActive || conversationReturning || conversationRecoveredId) return;
  await faceTracking.command('stop');
  conversationMode = input.value;
  localStorage.setItem('so101-conversation-mode', conversationMode);
  conversationSpeakerIndex = storedSpeakerIndex();
  renderConversationSpeaker();
  renderConversationMode();
  if (!conversationEntryReady) return;
  conversationCall.disabled = true;
  if (conversationMode !== 'realtime') {
    setConversationPhase('idle', 'Lokale Sprachmodelle werden vorbereitet …');
    try { await prepareConversation(); }
    catch (error) { setConversationPhase('error', `Lokaler Sprachmodus: ${error.message}`); return; }
  }
  await refreshConversationStatus();
}));

async function preserveRecoveredConversation() {
  const sessionId = sessionStorage.getItem('so101-conversation-motion-id');
  if (!sessionId) return;
  try {
    const motion = await readJson(await fetch('/api/conversation/motion/status', { cache: 'no-store' }));
    if (motion.sessionId !== sessionId || !motion.active || motion.state !== 'holding') return;
    await postConversationMotion('heartbeat', { sessionId });
    if (conversationHeartbeat || conversationActive || activeView !== 'conversation') return;
    conversationHeartbeat = setInterval(() => {
      if (conversationActive || conversationReturning || activeView !== 'conversation' ||
          sessionStorage.getItem('so101-conversation-motion-id') !== sessionId) {
        clearInterval(conversationHeartbeat);
        conversationHeartbeat = null;
        return;
      }
      void postConversationMotion('heartbeat', { sessionId }).catch(() => {
        clearInterval(conversationHeartbeat);
        conversationHeartbeat = null;
        if (conversationEntryReady) void refreshConversationStatus();
      });
    }, 5000);
  } catch {
    // The status refresh below reports an unreachable or stopped controller.
  }
}

async function refreshConversationStatus() {
  if (!conversationEntryReady) return;
  try {
    const savedSessionId = sessionStorage.getItem('so101-conversation-motion-id');
    const motionPath = '/api/conversation/motion/status' +
      (savedSessionId ? `?sessionId=${encodeURIComponent(savedSessionId)}` : '');
    const [result, motion] = await Promise.all([
      fetch(`/api/conversation/status?mode=${conversationMode}&voice=${encodeURIComponent(conversationSpeakerValue())}`,
        { cache: 'no-store' }).then(readJson),
      fetch(motionPath, { cache: 'no-store' }).then(readJson),
    ]);
    const realtime = conversationMode === 'realtime';
    const piper = conversationMode === 'piper';
    const voiceOnlyAvailable = result.followerPortAvailable === false && !motion.active;
    const introReady = result.introReady || voiceOnlyAvailable;
    const voiceReady = realtime ? result.realtimeReady : piper ? result.piperReady : result.ttsReady;
    setStatusItem(voiceStatus, realtime
      ? voiceReady ? 'ChatGPT Realtime bereit' : 'ChatGPT API-Schlüssel fehlt'
      : piper ? voiceReady ? 'Piper bereit' : 'Piper nicht bereit'
        : voiceReady ? 'CustomVoice bereit' : 'CustomVoice nicht bereit', voiceReady ? 'ready' : 'muted');
    if (!conversationActive && !conversationReturning) {
      const ownedSession = sessionStorage.getItem('so101-conversation-motion-id') === motion.sessionId;
      const completedSession = motion.occupied && !motion.active && motion.state === 'stopped' &&
        motion.followerTorqueHolding === true && motion.returnAvailable === true;
      conversationRecoveredId = !voiceOnlyAvailable && motion.occupied && motion.sessionId && (ownedSession || completedSession)
        ? motion.sessionId : null;
      if (completedSession && motion.sessionId) {
        sessionStorage.setItem('so101-conversation-motion-id', motion.sessionId);
      }
      if (!motion.occupied) sessionStorage.removeItem('so101-conversation-motion-id');
      if (!motion.active && conversationHeartbeat) {
        clearInterval(conversationHeartbeat);
        conversationHeartbeat = null;
      }
      conversationCall.disabled = voiceOnlyAvailable
        ? !voiceReady || (!realtime && !result.dialogueReady)
        : motion.occupied ? !conversationRecoveredId ||
        (completedSession && !conversationRecoverySupported)
        : !voiceReady || (!realtime && !result.dialogueReady) || !introReady;
      setConversationPhase('idle', voiceOnlyAvailable
        ? voiceReady && (realtime || result.dialogueReady)
          ? motion.error
            ? 'Ohne SO-101 bereit · früherer Follower-Halt unbestätigt.'
            : 'Ohne SO-101 bereit · nur Sprache.'
          : realtime ? 'OPENAI_API_KEY fehlt auf dem UI-Server.'
            : result.dialogueReason || 'Sprachmodelle werden vorbereitet …'
        : motion.occupied
        ? motion.error || (completedSession
          ? conversationRecoverySupported ? 'Bereit für die Rückfahrt.' : 'Rückfahrt nach Seitenwechsel erfordert ein Dienst-Update.'
          : motion.active ? 'Ein Gespräch ist noch aktiv.' : 'Rückfahrt für diese Sitzung nicht verfügbar.')
        : voiceReady && (realtime || result.dialogueReady) && introReady
        ? 'Bereit für ein Gespräch'
        : !result.introReady ? 'Intro-Aufnahme oder Bewegungscontroller fehlt.'
          : realtime ? 'OPENAI_API_KEY fehlt auf dem UI-Server.'
            : result.dialogueReason || 'Sprachmodelle werden vorbereitet …');
    }
  } catch {
    conversationRecoveredId = null;
    setStatusItem(voiceStatus, 'Sprachdienst nicht erreichbar', 'muted');
    if (!conversationActive && !conversationReturning) {
      conversationCall.disabled = true;
      setConversationPhase('idle', 'Gesprächsdienst nicht erreichbar.');
    }
  }
}

async function endRecoveredConversation() {
  const sessionId = conversationRecoveredId;
  if (!sessionId) return;
  conversationCall.disabled = true;
  try {
    const motion = await readJson(await fetch('/api/conversation/motion/status', { cache: 'no-store' }));
    if (motion.sessionId !== sessionId) {
      throw new Error('Gesprächssitzung hat sich geändert.');
    }
    conversationMotionId = sessionId;
    if (motion.active) {
      clearInterval(conversationHeartbeat);
      conversationHeartbeat = null;
      conversationMotionId = sessionId;
      conversationRecoveredId = null;
      conversationActive = true;
      realtimeTaskEverStarted = motion.taskWasStarted === true;
      if (motion.state === 'task') realtimeTaskActive = true;
      await endConversation();
      return;
    }
    if (motion.state !== 'stopped' || motion.followerTorqueHolding !== true) {
      throw new Error(motion.error || 'Follower-Halt konnte nicht bestätigt werden.');
    }
    await postConversationMotion('return-stopped', { sessionId });
    conversationMotionId = sessionId;
    conversationRecoveredId = null;
    conversationReturning = true;
    setConversationPhase('intro', 'Roboter fährt zur Anfangspose · hier stoppen');
    conversationCall.disabled = false;
    const completed = await waitForConversationReturn(sessionId);
    const result = completed ? await stopConversationMotion(true) : await conversationReturnCancel;
    conversationReturning = false;
    setConversationPhase('idle', result?.returnedToStart
      ? 'Anfangspose erreicht · Follower hält die Position.'
      : 'Rückfahrt gestoppt · Follower hält die Position.');
    await refreshConversationStatus();
  } catch (error) {
    let stopped;
    if (conversationMotionId) {
      try { stopped = await stopConversationMotion(false); }
      catch (stopError) { error = stopError; }
    }
    conversationReturning = false;
    if (stopped?.followerTorqueHolding === true) {
      conversationRecoveredId = null;
      setConversationPhase('idle', 'Gespräch beendet · Rückfahrt unterbrochen · Follower hält die Position.');
      conversationCall.disabled = false;
      return;
    }
    conversationRecoveredId = conversationMotionId ? null : sessionId;
    setConversationPhase('error', `Rückfahrt fehlgeschlagen: ${error.message}`);
    conversationCall.disabled = Boolean(conversationMotionId);
  }
}

async function releaseModelSession(signal) {
  const deadline = Date.now() + 30_000;
  while (true) {
    const response = await fetch('/api/session', { method: 'DELETE', signal });
    if (response.status !== 409) return readJson(response);
    const detail = (await response.json().catch(() => ({}))).detail;
    if (detail !== 'Ein Modelllauf läuft noch.' ||
        ['running', 'stopping'].includes(status.taskRun?.state) || Date.now() >= deadline) {
      throw new Error(detail || 'Modellsitzung ist noch belegt.');
    }
    if (activeView === 'conversation') setConversationPhase('idle', 'Modellvorgang wird abgeschlossen …');
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
}

async function prepareConversation() {
  if (conversationMode === 'realtime') return;
  const response = await fetch('/api/conversation/prepare', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: conversationMode, voice: conversationMode === 'piper'
      ? conversationSpeakerValue() : 'Thorsten' }),
  });
  if (response.status === 404) {
    // The running backend may still be the previous version until a safe restart.
    conversationRecoverySupported = false;
    const result = await readJson(await fetch('/api/conversation/status', { cache: 'no-store' }));
    if (!result.dialogueReady || !(conversationMode === 'piper' ? result.piperReady : result.ttsReady) ||
        (result.followerPortAvailable !== false && !result.introReady)) {
      throw new Error(result.dialogueReason || 'Gesprächsmodelle sind nicht bereit.');
    }
    return;
  }
  await readJson(response);
  conversationRecoverySupported = true;
}

async function initializeConversation() {
  if (conversationActive || conversationReturning || conversationEntryReady || conversationEntryPending) return;
  conversationCall.disabled = true;
  setConversationPhase('idle', 'Gespräch wird vorbereitet …');
  if (phase !== 'idle') {
    setConversationPhase('idle', 'Modellvorgang läuft noch. Bitte kurz warten.');
    return;
  }
  conversationEntryPending = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 45_000);
  try {
    // The first render after a reload has an empty status. Consult the
    // backend before deciding whether an existing policy should be unloaded.
    status = await readJson(await fetch('/api/status', { cache: 'no-store', signal: controller.signal }));
    const keepMolmo = keepMolmoForConversation(conversationMode, status);
    if (!keepMolmo) await releaseModelSession(controller.signal);
    cameraGeneration++;
    cameraReady = false;
    if (!keepMolmo) {
      status.modelSession = null;
      status.cameraModel = null;
    }
    await ensureConversationCameras();
    clearTimeout(timeout);
    const motion = await readJson(await fetch('/api/conversation/motion/status', { cache: 'no-store' }));
    const connection = await readJson(await fetch('/api/conversation/status?mode=realtime', { cache: 'no-store' }));
    if (!motion.occupied || (connection.followerPortAvailable === false && !motion.active)) {
      if (activeView === 'conversation') setConversationPhase('idle', 'Gesprächsmodelle werden geladen …');
      await prepareConversation();
    }
    if (activeView === 'conversation') {
      conversationEntryReady = true;
      await refreshConversationStatus();
    }
  } catch (error) {
    if (activeView === 'conversation') setConversationPhase('idle', controller.signal.aborted
      ? 'Freigabe dauert zu lange. Bitte Verbindung prüfen; Start bleibt gesperrt.'
      : `Gespräch noch gesperrt: ${error.message}`);
  } finally {
    clearTimeout(timeout);
    conversationEntryPending = false;
    renderConversationMode();
    render();
  }
}
void initializeConversation();
void preserveRecoveredConversation();

async function postConversationMotion(path, payload) {
  const response = await fetch(`/api/conversation/motion/${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json',
      ...(path === 'start' ? { 'x-so101-conversation': 'operator-call' } :
          path === 'return-stopped' ? { 'x-so101-conversation': 'operator-end' } : {}) },
    body: JSON.stringify(payload),
    ...(path === 'level' ? { signal: AbortSignal.timeout(1000) } : {}),
  });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || `HTTP ${response.status}`);
  return response.json();
}

async function stopConversationMotion(returnToStart = false) {
  clearInterval(conversationHeartbeat);
  conversationHeartbeat = null;
  const sessionId = conversationMotionId;
  if (sessionId) {
    const forgetExitedSession = () => {
      if (conversationMotionId === sessionId) conversationMotionId = null;
      if (sessionStorage.getItem('so101-conversation-motion-id') === sessionId) {
        sessionStorage.removeItem('so101-conversation-motion-id');
      }
    };
    try {
      const result = await postConversationMotion('stop', { sessionId, returnToStart });
      forgetExitedSession();
      return result;
    } catch (error) {
      try {
        const state = await readJson(await fetch('/api/conversation/motion/status', { cache: 'no-store' }));
        if (state.sessionId === sessionId && !state.active) forgetExitedSession();
      } catch { /* Keep the session until its exit can be confirmed. */ }
      throw error;
    }
  }
  return null;
}

async function waitForConversationIntro(generation, { quiet = false } = {}) {
  while (conversationActive && generation === conversationGeneration) {
    const state = await readJson(await fetch('/api/conversation/motion/status', { cache: 'no-store' }));
    if (state.sessionId !== conversationMotionId) throw new Error('Intro-Sitzung wurde ersetzt.');
    if (state.state === 'holding') {
      conversationIntroCompletedId = state.sessionId;
      // This is the final auto-start gate for Realtime face tracking. Refresh
      // it here instead of relying on opening the conversation settings.
      render();
      return;
    }
    if (state.state === 'failed' || state.state === 'stopped') {
      throw new Error(state.error || 'Intro-Bewegung wurde abgebrochen.');
    }
    if (!quiet) setConversationPhase('intro', state.state === 'positioning'
      ? 'Roboter fährt zur Anfangspose …' : state.state === 'intro'
        ? 'Intro läuft …' : 'Intro wird vorbereitet …');
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
}

async function waitForConversationReturn(sessionId) {
  const deadline = performance.now() + 90_000;
  while (conversationReturning && conversationMotionId === sessionId) {
    if (performance.now() > deadline) throw new Error('Rückfahrt hat das Zeitlimit überschritten.');
    const state = await readJson(await fetch('/api/conversation/motion/status', { cache: 'no-store' }));
    if (!conversationReturning) return false;
    if (state.sessionId !== sessionId) throw new Error('Rückfahrt-Sitzung wurde ersetzt.');
    if (state.state === 'failed') throw new Error(state.error || 'Rückfahrt wurde abgebrochen.');
    if (state.state === 'stopped' && !state.active) return true;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return false;
}

async function speakConversation(text, signal, voice = conversationSpeakerValue()) {
  signal.throwIfAborted();
  const response = await fetch('/api/conversation/speak', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, speaker: conversationMode === 'local' ? voice : 'Ryan',
      engine: conversationMode === 'piper' ? 'piper' : 'qwen',
      voice: conversationMode === 'piper' ? voice : 'Thorsten', language: conversationLanguage }), signal,
  });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || `HTTP ${response.status}`);
  const audioBlob = await response.blob();
  signal.throwIfAborted();
  const url = URL.createObjectURL(audioBlob);
  conversationAudio?.pause();
  conversationAudio = new Audio(url);
  const player = conversationAudio;
  const analyser = conversationAudioContext.createAnalyser();
  analyser.fftSize = 1024;
  const source = conversationAudioContext.createMediaElementSource(player);
  source.connect(analyser);
  analyser.connect(conversationAudioContext.destination);
  const stopWaveform = conversationWaveform.observeAnalyser(analyser, {
    context: conversationAudioContext, player, isCurrent: () => conversationAudio === player,
  });
  const levels = new Float32Array(analyser.fftSize);
  let levelTimer = null;
  let levelPending = false;
  let levelRequest = Promise.resolve();
  const finished = new Promise((resolve, reject) => {
    player.addEventListener('ended', resolve, { once: true });
    player.addEventListener('error', () => reject(new Error('Audiowiedergabe fehlgeschlagen.')), { once: true });
    signal.addEventListener('abort', () => { player.pause(); reject(signal.reason); }, { once: true });
  });
  try {
    await player.play();
    levelTimer = setInterval(() => {
      if (!conversationMotionId || player.paused || levelPending) return;
      analyser.getFloatTimeDomainData(levels);
      let power = 0;
      for (const sample of levels) power += sample * sample;
      const level = Math.min(1, Math.sqrt(power / levels.length) * 8);
      levelPending = true;
      levelRequest = postConversationMotion('level', { sessionId: conversationMotionId, level })
        .catch((error) => {
          if (!conversationActive) return;
          setConversationPhase('error', `Greifer: ${error.message}`);
          void endConversation(true);
        })
        .finally(() => { levelPending = false; });
    }, 60);
    await finished;
  } catch (error) {
    if (error.name === 'NotAllowedError') throw new Error('Audiowiedergabe wurde vom Browser blockiert.');
    throw error;
  } finally {
    stopWaveform();
    clearInterval(levelTimer);
    await levelRequest;
    if (conversationMotionId) {
      try { await postConversationMotion('speech-end', { sessionId: conversationMotionId }); }
      catch (error) {
        if (conversationActive) {
          setConversationPhase('error', `Greifer: ${error.message}`);
          void endConversation(true);
        }
      }
    }
    source.disconnect();
    analyser.disconnect();
    URL.revokeObjectURL(url);
    if (conversationAudio === player) conversationAudio = null;
  }
}

function stopRealtimeSession() {
  conversationWaveform.stop();
  void localConversation.close().catch(error => {
    conversationTaskFeedback.hidden = false;
    conversationTaskFeedback.textContent = `Lokales Gespräch konnte nicht geschlossen werden: ${error.message}`;
  });
  realtimeWebSearch.stop();
  realtimeTaskFeedback.reset();
  realtimeTaskCalls.clear();
  realtimeLevelTimer?.();
  realtimeLevelTimer = null;
  clearInterval(realtimeTaskPoll);
  realtimeTaskPoll = null;
  realtimeMolmoPreloadWarning = '';
  realtimeSpeaking = false;
  realtimeAudioElement?.pause();
  if (realtimeAudioElement) realtimeAudioElement.srcObject = null;
  realtimeAudioElement = null;
  realtimeChannel?.close();
  realtimeChannel = null;
  realtimePeer?.close();
  realtimePeer = null;
  realtimeSpeechMeter?.disconnect();
  realtimeSpeechMeter = null;
}

function sendRealtimeEvent(payload) {
  if (realtimeChannel?.readyState !== 'open') throw new Error('Realtime-Datenkanal ist geschlossen.');
  if (payload.type === 'response.create') console.info('[Realtime]', JSON.stringify({
    stage: 'response_requested', purpose: payload.response?.metadata?.purpose || 'dialogue',
  }));
  realtimeChannel.send(JSON.stringify(payload));
}

async function logRealtimeAudioStats(stage) {
  const peer = realtimePeer;
  if (!peer?.getStats) return;
  try {
    const reports = await peer.getStats();
    if (peer !== realtimePeer) return;
    for (const report of reports.values()) {
      if (report.type !== 'inbound-rtp' || report.kind !== 'audio') continue;
      console.info('[Realtime]', JSON.stringify({ stage: 'audio_transport', at: stage,
        packetsReceived: report.packetsReceived, packetsLost: report.packetsLost,
        jitter: report.jitter, concealedSamples: report.concealedSamples,
        concealmentEvents: report.concealmentEvents,
      }));
    }
  } catch { /* Closing a peer can invalidate a pending stats read. */ }
}

async function handleRealtimeTaskCall(call, generation) {
  if (!call.call_id || realtimeTaskCalls.has(call.call_id)) return;
  realtimeTaskCalls.add(call.call_id);
  console.info('[Realtime→Molmo]', JSON.stringify({ stage: 'tool_received', callId: call.call_id }));
  let result;
  try {
    if (!conversationActive || generation !== conversationGeneration) return;
    const args = JSON.parse(call.arguments || '{}');
    if (['get_project_info', 'get_creator_info'].includes(call.name)) {
      const creatorInfo = call.name === 'get_creator_info';
      if (!args || Array.isArray(args) || typeof args !== 'object' || Object.keys(args).length) {
        throw new Error('Hintergrundinformationen benötigen keine Argumente.');
      }
      result = await readJson(await fetch(`/api/conversation/realtime/${creatorInfo ? 'creator-info' : 'project-info'}`, {
        method: 'POST', headers: { 'X-SO101-Conversation': 'realtime-tool' },
        signal: AbortSignal.timeout(12_000),
      }));
      if (!conversationActive || generation !== conversationGeneration) return;
      const message = { type: 'conversation.item.create', item: {
        type: 'function_call_output', call_id: call.call_id, output: JSON.stringify(result),
      } };
      if (new TextEncoder().encode(JSON.stringify(message)).length > (realtimePeer?.sctp?.maxMessageSize || 65_536)) {
        throw new Error('Hintergrundinformationen überschreiten das Nachrichtenlimit der Verbindung.');
      }
      sendRealtimeEvent(message);
      if (creatorInfo) realtimeTaskFeedback.creatorInfoReady();
      else realtimeTaskFeedback.projectInfoReady();
      return;
    }
    if (call.name === 'search_web') {
      result = await realtimeWebSearch.search(args.query);
      if (!conversationActive || generation !== conversationGeneration) return;
      const message = { type: 'conversation.item.create', item: {
        type: 'function_call_output', call_id: call.call_id, output: JSON.stringify(result),
      } };
      if (new TextEncoder().encode(JSON.stringify(message)).length > (realtimePeer?.sctp?.maxMessageSize || 65_536)) {
        throw new Error('Suchergebnis überschreitet das Nachrichtenlimit der Verbindung.');
      }
      sendRealtimeEvent(message);
      realtimeTaskFeedback.searchReady();
      return;
    }
    if (call.name === 'look_at_scene') {
      const snapshot = await readJson(await fetch('/api/conversation/realtime/scene', {
        method: 'POST', headers: { 'X-SO101-Conversation': 'realtime-tool' },
        signal: AbortSignal.timeout(12_000),
      }));
      if (!conversationActive || generation !== conversationGeneration) return;
      const messages = sceneMessages(snapshot, call.call_id);
      const maxBytes = realtimePeer?.sctp?.maxMessageSize || 65_536;
      if (messages.some(message => new TextEncoder().encode(JSON.stringify(message)).length > maxBytes)) {
        throw new Error('Kamerabild überschreitet das Nachrichtenlimit der Verbindung.');
      }
      for (const message of messages) sendRealtimeEvent(message);
      realtimeTaskFeedback.sceneReady();
      return;
    }
    if (!conversationMotionId || conversationVoiceOnly) {
      throw new Error('Der Gesprächsarm ist nicht für eine Aufgabe bereit.');
    }
    if (call.name === 'reset_robot') {
      result = await resetConversationRobot(call.call_id);
    } else {
      if (conversationRestartPending) throw new Error('Roboter wird zurückgesetzt; danach neuen Auftrag geben.');
      result = await readJson(await fetch('/api/conversation/task/start', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-SO101-Conversation': 'realtime-tool' },
        body: JSON.stringify({ sessionId: conversationMotionId, callId: call.call_id, instruction: args.instruction }),
      }));
      if (!conversationActive || generation !== conversationGeneration) return;
      status.taskRun = result.taskRun;
      realtimeTaskActive = true;
      realtimeTaskLastState = result.taskRun?.state || 'loading';
      realtimeTaskEverStarted = true;
      const message = result.status === 'updated'
        ? 'MolmoAct2 übernimmt die neue Anweisung.' : 'MolmoAct2 bereitet den Auftrag vor.';
      setConversationPhase('thinking', message);
      realtimeTaskFeedback.update(result.status, message);
    }
  } catch (error) {
    result = { error: error.message };
    if (!['look_at_scene', 'search_web', 'get_project_info', 'get_creator_info'].includes(call.name) && conversationActive && generation === conversationGeneration) {
      setConversationPhase('error', `MolmoAct2: ${error.message}`);
      realtimeTaskFeedback.update('failed', `Auftrag nicht gestartet: ${error.message}`);
    }
  }
  if (!conversationActive || generation !== conversationGeneration) return;
  sendRealtimeEvent({ type: 'conversation.item.create', item: {
    type: 'function_call_output', call_id: call.call_id, output: JSON.stringify(result),
  } });
  if (['get_project_info', 'get_creator_info'].includes(call.name)) {
    if (call.name === 'get_creator_info') realtimeTaskFeedback.creatorInfoReady();
    else realtimeTaskFeedback.projectInfoReady();
    return;
  }
  if (call.name === 'search_web') {
    realtimeTaskFeedback.searchReady();
    return;
  }
  if (call.name === 'look_at_scene') {
    realtimeTaskFeedback.sceneReady();
    return;
  }
  if (call.name === 'reset_robot' && !result.error) {
    realtimeTaskFeedback.update('reset', 'Intro-Endhaltung eingenommen. Follower hält die gemessene Position; Gespräch und Modell bleiben aktiv.', { speak: true });
  }
  // Ordinary movement was already announced; speak again only on failure.
  if (result.error) realtimeTaskFeedback.update('failed', `Auftrag nicht gestartet: ${result.error}`, { speak: true });
}

async function pollRealtimeTask(generation) {
  if (!conversationActive || generation !== conversationGeneration || !realtimeTaskActive || conversationRestartPending) return;
  const taskAtPoll = status.taskRun;
  const resetEpochAtPoll = conversationResetEpoch;
  try {
    const [task, motion] = await Promise.all([
      readJson(await fetch('/api/task/status', { cache: 'no-store' })),
      readJson(await fetch('/api/conversation/motion/status', { cache: 'no-store' })),
    ]);
    if (!conversationActive || generation !== conversationGeneration) return;
    if (conversationRestartPending || conversationResetEpoch !== resetEpochAtPoll || status.taskRun !== taskAtPoll) return;
    status.taskRun = task.taskRun;
    if (task.taskRun && ['loading', 'running', 'stopping'].includes(task.taskRun.state)) {
      if (task.taskRun.state !== realtimeTaskLastState) {
        realtimeTaskLastState = task.taskRun.state;
        realtimeTaskFeedback.update(task.taskRun.state, `MolmoAct2: ${task.taskRun.message}`);
      }
      conversationTaskFeedback.hidden = false;
      conversationTaskFeedback.textContent = `MolmoAct2: ${task.taskRun.message}`;
      if (!realtimeSpeaking) setConversationPhase('thinking', `MolmoAct2: ${task.taskRun.message}`);
      return;
    }
    realtimeTaskActive = false;
    realtimeSpeechGripperAvailable = motion.speechGripperAvailable !== false;
    if (motion.state !== 'holding' || task.taskRun?.state === 'failed') {
      setConversationPhase('error', `MolmoAct2: ${task.taskRun?.message || motion.error || 'Follower-Halt prüfen.'}`);
      realtimeTaskFeedback.update('failed',
        `MolmoAct2-Auftrag fehlgeschlagen: ${task.taskRun?.message || motion.error || 'Follower-Halt prüfen.'}`,
        { speak: true });
      return;
    }
    realtimeTaskFeedback.update('stopped', 'MolmoAct2-Run gestoppt · Modell bleibt geladen · Gespräch läuft weiter. Ein Aufgabenerfolg wurde nicht geprüft.');
    setConversationPhase('listening', realtimeSpeechGripperAvailable
      ? 'MolmoAct2 angehalten · ich höre zu …'
      : 'MolmoAct2 angehalten · Greifer bleibt in seiner Position.');
  } catch (error) {
    setConversationPhase('error', `Aufgabenstatus: ${error.message}`);
  }
}

let localTaskPollPending = false;
async function pollLocalTask(generation) {
  if (localTaskPollPending || !conversationActive || generation !== conversationGeneration || !realtimeTaskActive || conversationRestartPending) return;
  localTaskPollPending = true;
  const epoch = conversationResetEpoch;
  const taskAtPoll = status.taskRun;
  try {
    const [task, motion] = await Promise.all([
      readJson(await fetch('/api/task/status', { cache: 'no-store' })),
      readJson(await fetch('/api/conversation/motion/status', { cache: 'no-store' })),
    ]);
    if (!conversationActive || generation !== conversationGeneration || conversationRestartPending ||
        epoch !== conversationResetEpoch || status.taskRun !== taskAtPoll) return;
    const finished = realtimeTaskActive && !['loading', 'running', 'stopping'].includes(task.taskRun?.state);
    status.taskRun = task.taskRun;
    realtimeTaskActive = ['loading', 'running', 'stopping'].includes(task.taskRun?.state);
    realtimeTaskLastState = task.taskRun?.state;
    realtimeSpeechGripperAvailable = motion.speechGripperAvailable !== false;
    conversationTaskFeedback.hidden = false;
    conversationTaskFeedback.textContent = realtimeTaskActive ? `MolmoAct2: ${task.taskRun.message}`
      : task.taskRun?.state === 'failed' || motion.state !== 'holding'
        ? `MolmoAct2: ${task.taskRun?.message || motion.error || 'Follower-Halt prüfen.'}`
        : 'MolmoAct2 angehalten · Gespräch läuft weiter. Ein Aufgabenerfolg wurde nicht geprüft.';
    if (finished) {
      localTaskNotice = true;
      if (conversationPhase === 'listening' && !conversationSpeechDetected && !conversationRequest) {
        stopConversationRecording();
        listenForConversation(generation);
      }
    }
    render();
  } catch (error) {
    conversationTaskFeedback.textContent = `Aufgabenstatus: ${error.message}`;
  } finally { localTaskPollPending = false; }
}

function handleRealtimeEvent(event, generation) {
  if (!conversationActive || generation !== conversationGeneration) return;
  let data;
  try { data = JSON.parse(event.data); } catch { return; }
  if (data.type === 'session.created' || data.type === 'session.updated') {
    console.info('[Realtime→Molmo]', JSON.stringify({ stage: data.type,
      tools: (data.session?.tools || []).map(tool => tool.name), model: data.session?.model,
      turnDetection: data.session?.audio?.input?.turn_detection }));
  }
  if (['response.created', 'output_audio_buffer.started', 'output_audio_buffer.stopped',
    'output_audio_buffer.cleared', 'input_audio_buffer.committed', 'error'].includes(data.type)) {
    console.info('[Realtime]', JSON.stringify({ stage: data.type,
      responseId: data.response?.id || data.response_id, purpose: data.response?.metadata?.purpose,
      error: data.error?.message }));
  }
  if (data.type === 'response.done') {
    console.info('[Realtime→Molmo]', JSON.stringify({ stage: 'response_done', status: data.response?.status,
      responseId: data.response?.id, statusDetails: data.response?.status_details,
      output: (data.response?.output || []).map(item => ({ type: item.type, name: item.name,
        transcript: (item.content || []).map(part => part.transcript || '').join('').slice(0, 300) })) }));
  }
  if (data.type === 'response.created') realtimeTaskFeedback.responseStarted();
  switch (data.type) {
    case 'input_audio_buffer.speech_started':
      realtimeTaskFeedback.userSpeechStarted();
      setConversationPhase('listening', 'Ich höre dich …');
      break;
    case 'input_audio_buffer.committed':
      realtimeTaskFeedback.userTurnCommitted(data.item_id);
      break;
    case 'input_audio_buffer.speech_stopped':
    case 'response.created':
      setConversationPhase('thinking', `${conversationSpeakerName()} denkt nach …`);
      break;
    case 'output_audio_buffer.started':
      void logRealtimeAudioStats(data.type);
      realtimeTaskFeedback.playbackStarted(data.response_id);
      realtimeSpeaking = true;
      setConversationPhase('speaking', `${conversationSpeakerName()} spricht …`);
      break;
    case 'output_audio_buffer.stopped':
    case 'output_audio_buffer.cleared':
      void logRealtimeAudioStats(data.type);
      realtimeTaskFeedback.playbackFinished(data.response_id);
      realtimeSpeaking = realtimeTaskFeedback.playing.size > 0;
      if (!realtimeSpeaking) setConversationPhase('listening', 'Ich höre zu …');
      break;
    case 'response.output_audio.delta':
    case 'response.output_audio_transcript.delta':
      realtimeSpeaking = true;
      setConversationPhase('speaking', `${conversationSpeakerName()} spricht …`);
      break;
    case 'response.done':
      if (data.response?.status === 'failed') {
        setConversationPhase('error', `ChatGPT Realtime: ${data.response.status_details?.error?.message || 'Antwort fehlgeschlagen.'}`);
        void endConversation(true);
        break;
      }
      const calls = (data.response?.output || []).filter((item) => item.type === 'function_call' && ['execute_molmo_task', 'reset_robot', 'look_at_scene', 'search_web', 'get_project_info', 'get_creator_info'].includes(item.name));
      if (calls.length && data.response?.status === 'completed') {
        realtimeSpeaking = realtimeTaskFeedback.playing.size > 0;
        realtimeTaskFeedback.toolStarted();
        // One robot operation per turn. A reset takes precedence over movement;
        // answer every extra call so none remain unresolved in the dialogue.
        const motorCalls = calls.filter(call => ['execute_molmo_task', 'reset_robot'].includes(call.name));
        const selected = motorCalls.find(call => call.name === 'reset_robot') || motorCalls[0];
        for (const extra of motorCalls.filter(call => call !== selected)) {
          if (!extra.call_id || realtimeTaskCalls.has(extra.call_id)) continue;
          realtimeTaskCalls.add(extra.call_id);
          sendRealtimeEvent({ type: 'conversation.item.create', item: {
            type: 'function_call_output', call_id: extra.call_id,
            output: JSON.stringify({ error: 'Nur eine Roboteraktion pro Gesprächsschritt. Nach dem Reset auf einen neuen Auftrag warten.' }),
          } });
        }
        // Read-only observations can accompany the selected motor operation.
        const work = [...(selected ? [selected] : []), ...calls.filter(call => ['look_at_scene', 'search_web', 'get_project_info', 'get_creator_info'].includes(call.name))];
        void (async () => {
          for (const call of work) {
            if (!conversationActive || generation !== conversationGeneration) return;
            await handleRealtimeTaskCall(call, generation);
          }
        })().finally(() => {
          if (conversationActive && generation === conversationGeneration) realtimeTaskFeedback.toolFinished();
        });
        break;
      }
      // Generation completion can precede audible playback completion. The
      // remote audio envelope owns mouth movement, independently of these events.
      realtimeSpeaking = realtimeTaskFeedback.playing.size > 0;
      if (!realtimeSpeaking) setConversationPhase('listening', 'Ich höre zu …');
      break;
    case 'error':
      setConversationPhase('error', `ChatGPT Realtime: ${data.error?.message || 'Sitzungsfehler'}`);
      void endConversation(true);
      break;
    default:
      break;
  }
  if (data.type === 'response.done' && conversationActive) realtimeTaskFeedback.responseFinished();
}

async function startRealtimeSession(media, generation) {
  realtimeWebSearch.reset();
  const response = await fetch('/api/conversation/realtime/token', {
    method: 'POST', headers: { 'x-so101-conversation': 'operator-call', 'Content-Type': 'application/json' },
    body: JSON.stringify({ voice: conversationSpeakerValue(), voiceOnly: conversationVoiceOnly, language: conversationLanguage }),
    signal: AbortSignal.timeout(25_000),
  });
  const token = await readJson(response);
  if (!conversationActive || generation !== conversationGeneration) return;
  const peer = new RTCPeerConnection();
  realtimePeer = peer;
  peer.addTrack(media.getAudioTracks()[0], media);
  peer.ontrack = (event) => {
    if (!conversationActive || generation !== conversationGeneration || event.track.kind !== 'audio') return;
    const remoteStream = event.streams[0] || new MediaStream([event.track]);
    // A duplicate track notification must not detach and restart the player.
    if (realtimeAudioElement?.srcObject?.getAudioTracks().includes(event.track)) return;
    event.track.addEventListener('ended', () => {
      if (!conversationActive || generation !== conversationGeneration) return;
      setConversationPhase('error', 'ChatGPT Audioverbindung wurde beendet.');
      void endConversation(true);
    });
    const audio = document.createElement('audio');
    audio.autoplay = true;
    audio.playsInline = true;
    audio.srcObject = remoteStream;
    realtimeAudioElement?.pause();
    if (realtimeAudioElement) realtimeAudioElement.srcObject = null;
    realtimeAudioElement = audio;
    for (const type of ['playing', 'waiting', 'stalled', 'pause', 'ended', 'error']) {
      audio.addEventListener(type, () => {
        if (!conversationActive || generation !== conversationGeneration || realtimeAudioElement !== audio) return;
        console.info('[Realtime]', JSON.stringify({ stage: `audio_${type}`, time: audio.currentTime }));
        if (['waiting', 'stalled', 'error'].includes(type)) void logRealtimeAudioStats(type);
      });
    }
    void audio.play().catch((error) => {
      if (!conversationActive || generation !== conversationGeneration) return;
      const message = error.name === 'NotAllowedError'
        ? 'Der Browser blockiert die Audioausgabe. Bitte Audiowiedergabe für diese Seite erlauben.'
        : `Audioausgabe fehlgeschlagen: ${error.message}`;
      setConversationPhase('error', message);
      void endConversation(true);
    });
    conversationWaveform.observeStream(conversationAudioContext, remoteStream, {
      player: audio, isCurrent: () => conversationActive && generation === conversationGeneration && realtimeAudioElement === audio,
    });
    if (!conversationMotionId) return;
    realtimeLevelTimer?.();
    realtimeSpeechMeter?.disconnect();
    const meter = createSpeechMeter(conversationAudioContext, remoteStream);
    realtimeSpeechMeter = meter;
    const sessionId = conversationMotionId;
    realtimeLevelTimer = startSpeechLevelPump({
      read: () => audio.paused || audio.muted ? 0 : meter.read(),
      enabled: () => conversationActive && generation === conversationGeneration &&
        conversationMotionId === sessionId && !realtimeTaskActive && !conversationRestartPending && realtimeSpeechGripperAvailable,
      send: async (level) => {
        const resetEpoch = conversationResetEpoch;
        try { return await postConversationMotion('level', { sessionId, level }); }
        catch (error) {
          if (resetEpoch !== conversationResetEpoch || conversationRestartPending) return;
          throw error;
        }
      },
      onError: (error) => {
        if (!conversationActive || generation !== conversationGeneration) return;
        setConversationPhase('error', `Greifer: ${error.message}`);
        void endConversation(true);
      },
    });
  };
  peer.onconnectionstatechange = () => {
    if (peer === realtimePeer) console.info('[Realtime]', JSON.stringify({ stage: 'connection', state: peer.connectionState }));
    if (peer.connectionState !== 'failed' || !conversationActive || generation !== conversationGeneration) return;
    setConversationPhase('error', 'ChatGPT Realtime-Verbindung unterbrochen.');
    void endConversation(true);
  };
  const channel = peer.createDataChannel('oai-events');
  realtimeChannel = channel;
  let opened = false;
  channel.onopen = () => {
    if (!opened && conversationActive && generation === conversationGeneration) {
      opened = true;
      setConversationPhase('listening', realtimeMolmoPreloadWarning || 'Ich höre zu …');
      realtimeTaskPoll = setInterval(() => { void pollRealtimeTask(generation); }, 750);
      sendRealtimeEvent({ type: 'conversation.item.create', item: {
        type: 'message', role: 'system', content: [{ type: 'input_text', text: `${SPOKEN_BREVITY} ${languageInstruction(conversationLanguage)}` }],
      } });
      realtimeTaskFeedback.greet();
    }
  };
  channel.onclose = () => {
    if (!conversationActive || generation !== conversationGeneration) return;
    setConversationPhase('error', 'ChatGPT Realtime-Verbindung wurde beendet.');
    void endConversation(true);
  };
  channel.onmessage = (event) => handleRealtimeEvent(event, generation);
  const offer = await peer.createOffer();
  await peer.setLocalDescription(offer);
  const sdpResponse = await fetch('https://api.openai.com/v1/realtime/calls', {
    method: 'POST', headers: {
      Authorization: `Bearer ${token.value}`,
      'Content-Type': 'application/sdp',
    }, body: offer.sdp, signal: AbortSignal.timeout(30_000),
  });
  if (!sdpResponse.ok) throw new Error(`ChatGPT Realtime-Verbindung fehlgeschlagen (HTTP ${sdpResponse.status}).`);
  const sdp = await sdpResponse.text();
  if (!conversationActive || generation !== conversationGeneration) return;
  await peer.setRemoteDescription({ type: 'answer', sdp });
  await waitForRealtimeChannel(channel, peer);
}

async function answerConversation(text, generation) {
  if (!conversationActive || generation !== conversationGeneration) return;
  const request = new AbortController();
  conversationRequest = request;
  setConversationPhase('thinking', `${conversationSpeakerName()} denkt nach …`);
  try {
    await localConversation.turn(text, request.signal);
    if (conversationRequest === request) conversationRequest = null;
    if (conversationActive && generation === conversationGeneration) listenForConversation(generation);
  } catch (error) {
    if (request.signal.aborted || !conversationActive || generation !== conversationGeneration) return;
    setConversationPhase('error', `Lokales Gespräch: ${error.message}`);
    void endConversation(true);
  } finally {
    if (conversationRequest === request) conversationRequest = null;
  }
}

async function transcribeConversation(blob, generation) {
  if (!conversationActive || generation !== conversationGeneration) return;
  const request = new AbortController();
  conversationRequest = request;
  setConversationPhase('processing', 'Ich habe dich gehört …');
  try {
    const form = new FormData();
    const extension = blob.type.includes('mp4') ? 'mp4' : blob.type.includes('ogg') ? 'ogg' : 'webm';
    form.append('audio', blob, `conversation.${extension}`);
    if (conversationMode !== 'realtime') form.append('language', conversationLanguage);
    const result = await readJson(await fetch('/api/transcribe', { method: 'POST', body: form, signal: request.signal }));
    if (!conversationActive || generation !== conversationGeneration) return;
    const text = String(result.text || '').trim();
    if (text) await answerConversation(text, generation);
    else listenForConversation(generation);
  } catch (error) {
    if (request.signal.aborted || !conversationActive || generation !== conversationGeneration) return;
    setConversationPhase('error', `Transkription fehlgeschlagen: ${error.message}`);
    endConversation(true);
  } finally {
    if (conversationRequest === request) conversationRequest = null;
  }
}

function stopConversationRecording(submit = false) {
  conversationSpeechDetected = false;
  clearInterval(conversationMeter);
  clearTimeout(conversationTimer);
  conversationMeter = null;
  conversationTimer = null;
  const recorder = conversationRecorder;
  conversationRecorder = null;
  if (!recorder || recorder.state !== 'recording') return;
  if (submit) {
    const generation = conversationGeneration;
    recorder.addEventListener('stop', () => {
      const blob = new Blob(conversationChunks, { type: recorder.mimeType || 'audio/webm' });
      conversationChunks = [];
      if (blob.size) void transcribeConversation(blob, generation);
      else if (conversationActive) listenForConversation(generation);
    }, { once: true });
  }
  recorder.stop();
}

function listenForConversation(generation, quietWarning = false) {
  if (!conversationActive || generation !== conversationGeneration || !conversationStream || !conversationAnalyser) return;
  if (conversationMode !== 'realtime' && localTaskNotice && !conversationRequest) {
    localTaskNotice = false;
    const request = new AbortController();
    conversationRequest = request;
    setConversationPhase('thinking', 'Roboterstatus wird zusammengefasst …');
    void localConversation.feedback(request.signal).catch(error => {
      if (!request.signal.aborted && conversationActive && generation === conversationGeneration) {
        conversationTaskFeedback.textContent += ` Sprachausgabe des Status fehlgeschlagen: ${error.message}`;
      }
    }).finally(() => {
      if (conversationRequest === request) conversationRequest = null;
      if (!request.signal.aborted && conversationActive && generation === conversationGeneration) listenForConversation(generation);
    });
    return;
  }
  conversationSpeechDetected = false;
  const mimeType = preferredMimeType();
  const recorder = mimeType ? new MediaRecorder(conversationStream, { mimeType }) : new MediaRecorder(conversationStream);
  conversationRecorder = recorder;
  conversationChunks = [];
  recorder.addEventListener('dataavailable', (event) => { if (event.data.size) conversationChunks.push(event.data); });
  recorder.start();
  setConversationPhase('listening', quietWarning
    ? 'Noch keine Sprache erkannt. Falls du gesprochen hast, prüfe das Mikrofon.'
    : 'Ich höre zu …');
  const levels = new Float32Array(conversationAnalyser.fftSize);
  let noiseFloor = 0.002;
  let speechFrames = 0;
  let speechStarted = 0;
  let lastSpeech = 0;
  let peakLevel = 0;
  const start = performance.now();
  conversationMeter = setInterval(() => {
    if (!conversationActive || generation !== conversationGeneration) return;
    conversationAnalyser.getFloatTimeDomainData(levels);
    let sum = 0;
    for (const value of levels) sum += value * value;
    const rms = Math.sqrt(sum / levels.length);
    peakLevel = Math.max(peakLevel, rms);
    const now = performance.now();
    const speech = rms > Math.max(0.004, noiseFloor * 1.9);
    if (!speech && !speechStarted) noiseFloor = noiseFloor * 0.97 + rms * 0.03;
    speechFrames = speech ? speechFrames + 1 : 0;
    if (speechFrames >= 3 && !speechStarted) {
      speechStarted = now;
      conversationSpeechDetected = true;
      setConversationPhase('listening', 'Ich höre dich …');
    }
    if (speech && speechStarted) lastSpeech = now;
    if (speechStarted && now - speechStarted > 300 && now - lastSpeech > 1050) stopConversationRecording(true);
    if (now - start > 12_000) {
      if (speechStarted || peakLevel > 0.003) stopConversationRecording(true);
      else {
        recorder.addEventListener('stop', () => listenForConversation(generation, true), { once: true });
        stopConversationRecording();
      }
    }
  }, 50);
}

function cancelConversationReturn() {
  if (!conversationReturning || !conversationMotionId) return conversationStopping;
  conversationReturning = false;
  conversationCall.disabled = true;
  setConversationPhase('intro', 'Rückfahrt wird gestoppt …');
  conversationReturnCancel = stopConversationMotion(false)
    .then((result) => ({ ...result, cancelled: true }));
  return conversationReturnCancel;
}

function endConversation(keepMessage = false) {
  if (!conversationActive) return conversationStopping;
  conversationActive = false;
  conversationGeneration++;
  stopConversationRecording();
  conversationRequest?.abort();
  conversationRequest = null;
  stopRealtimeSession();
  conversationAudio?.pause();
  conversationAudio = null;
  conversationStream?.getTracks().forEach((track) => track.stop());
  conversationStream = null;
  void conversationAudioContext?.close();
  conversationAudioContext = null;
  conversationAnalyser = null;
  const voiceOnly = conversationVoiceOnly;
  const hadMotion = Boolean(conversationMotionId);
  const returnToStart = !keepMessage && Boolean(conversationMotionId);
  conversationReturning = returnToStart;
  conversationReturnCancel = null;
  setConversationPhase(keepMessage ? 'error' : 'intro', keepMessage
    ? conversationFeedback.textContent : returnToStart
      ? 'Gespräch beendet · Roboter fährt zur Anfangspose …' : 'Gespräch wird beendet …');
  conversationCall.disabled = true;
  conversationStopping = (async () => {
    await faceTracking.command('stop');
    const currentMotion = hadMotion
      ? await readJson(await fetch('/api/conversation/motion/status', { cache: 'no-store' })) : null;
    if (currentMotion && currentMotion.sessionId !== conversationMotionId) throw new Error('Gesprächsbewegung wurde ersetzt.');
    if (realtimeTaskActive || currentMotion?.state === 'task') {
      const stopResponse = await fetch('/api/task/stop', {
        method: 'POST', headers: { 'X-SO101-Stop': 'operator-click' },
      });
      if (stopResponse.ok) await readJson(stopResponse);
      else if (stopResponse.status !== 409) await readJson(stopResponse);
      for (let attempt = 0; attempt < 120; attempt++) {
        const task = await readJson(await fetch('/api/task/status', { cache: 'no-store' }));
        if (!task.taskRun || !['loading', 'running', 'stopping'].includes(task.taskRun.state)) break;
        await new Promise((resolve) => setTimeout(resolve, 250));
        if (attempt === 119) throw new Error('MolmoAct2-Stopp wurde nicht bestätigt.');
      }
      realtimeTaskActive = false;
    }
    if (!returnToStart) return stopConversationMotion(false);
    const sessionId = conversationMotionId;
    const state = await readJson(await fetch('/api/conversation/motion/status', { cache: 'no-store' }));
    if (state.sessionId !== sessionId) throw new Error('Gesprächsbewegung wurde ersetzt.');
    // An explicit end also interrupts positioning/the intro and returns home.
    // Never silently downgrade the operator's return request to a stationary stop.
    await postConversationMotion(state.state === 'stopped' && state.returnAvailable
      ? 'return-stopped' : 'return', { sessionId });
    conversationCall.disabled = false;
    setConversationPhase('intro', 'Roboter fährt zur Anfangspose · hier stoppen');
    const completed = await waitForConversationReturn(sessionId);
    if (!completed) return conversationReturnCancel;
    conversationReturning = false;
    conversationCall.disabled = true;
    return stopConversationMotion(true);
  })().then((result) => {
    if (keepMessage) return;
    setConversationPhase('idle', voiceOnly ? 'Gespräch beendet · ohne Roboter.'
      : !hadMotion ? 'Gespräch beendet.' : result?.returnedToStart
      ? 'Anfangspose erreicht · Follower hält die Position.'
      : result?.cancelled ? 'Rückfahrt gestoppt · Follower hält die Position.'
        : 'Gespräch beendet · Follower hält die Position.');
  }).catch(async (error) => {
    conversationReturning = false;
    let stopped;
    if (conversationMotionId) {
      try { stopped = await stopConversationMotion(false); }
      catch (stopError) { error = stopError; }
    }
    if (!keepMessage && stopped?.followerTorqueHolding === true) {
      conversationRecoveredId = null;
      setConversationPhase('idle', 'Gespräch beendet · Rückfahrt unterbrochen · Follower hält die Position.');
      return;
    }
    setConversationPhase('error', `Follower-Halt prüfen: ${error.message}`);
  }).finally(() => {
    // Keep the controller alive while stopping a policy and preparing the return.
    clearInterval(conversationHeartbeat);
    conversationHeartbeat = null;
    conversationReturning = false;
    conversationCall.disabled = Boolean(conversationMotionId);
    if (!keepMessage && !conversationMotionId) {
      setTimeout(() => { if (!conversationActive) void refreshConversationStatus(); }, 4000);
    }
  });
  return conversationStopping;
}

conversationCall.addEventListener('click', async () => {
  if (!conversationEntryReady) return;
  if (conversationRestartPending) {
    conversationRestartCancelled = true;
    if (conversationReturning) await cancelConversationReturn().catch(() => {});
    else if (conversationActive) await endConversation();
    return;
  }
  if (conversationReturning) { void cancelConversationReturn().catch(() => {}); return; }
  if (conversationRecoveredId) { void endRecoveredConversation(); return; }
  if (conversationActive) { endConversation(); return; }
  await startConversation();
});

conversationStartWithoutIntro.addEventListener('click', () => {
  void (async () => {
    if (conversationMode !== 'realtime') {
      stopConversationRecording();
      conversationRequest?.abort();
      conversationRequest = null;
      await localConversation.cancelTurn();
    }
    await resetConversationRobot(crypto.randomUUID(), 'operator-reset');
    if (conversationMode !== 'realtime' && conversationActive) listenForConversation(conversationGeneration);
  })().catch(error => {
    if (conversationMode !== 'realtime' && conversationActive) {
      setConversationPhase('error', `Roboter-Reset: ${error.message}`);
      void endConversation(true);
    }
  });
});

async function resetConversationRobot(callId, origin = 'realtime-tool') {
  if (!conversationActive || !conversationMotionId || conversationVoiceOnly || conversationReturning) {
    throw new Error('Reset erfordert ein aktives Robotergespräch.');
  }
  if (conversationRestartPending) throw new Error('Roboter wird bereits zurückgesetzt.');
  const sessionId = conversationMotionId;
  const generation = conversationGeneration;
  conversationRestartPending = true;
  localTaskNotice = false;
  conversationRestartCancelled = false;
  conversationResetEpoch++;
  conversationIntroCompletedId = null;
  renderConversationMode();
  try {
    setConversationPhase('thinking', 'Roboter fährt zur Intro-Endposition · Gespräch bleibt verbunden …');
    const result = await readJson(await fetch('/api/conversation/robot/reset', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-SO101-Conversation': origin },
      body: JSON.stringify({ sessionId, callId }),
    }));
    if (!conversationActive || generation !== conversationGeneration || sessionId !== conversationMotionId) return result;
    if (result.status !== 'reset' || result.followerTorqueHolding !== true || result.controllerRestarted !== true) throw new Error('Neustart des Motorcontrollers wurde nicht bestätigt.');
    realtimeTaskActive = false;
    realtimeTaskEverStarted = true;
    realtimeTaskLastState = 'stopped';
    status.taskRun = null;
    realtimeSpeechGripperAvailable = result.speechGripperAvailable !== false;
    conversationIntroCompletedId = sessionId;
    setConversationPhase('listening', 'Intro-Endhaltung · Follower hält die gemessene Position · bereit für einen neuen Auftrag.');
    if (['realtime', 'piper', 'local'].includes(conversationMode) && activeView === 'conversation') {
      faceTracking.rearmAfterReset(sessionId);
      render();
    }
    if (origin === 'operator-reset' && conversationMode === 'realtime') {
      realtimeTaskFeedback.update('reset', 'Roboter zurückgesetzt. Follower hält die Intro-Endhaltung; bereit für einen neuen Auftrag.');
    }
    return result;
  } catch (error) {
    if (conversationActive && generation === conversationGeneration) {
      setConversationPhase('error', `Roboter-Reset: ${error.message}`);
    }
    throw error;
  } finally {
    conversationRestartPending = false;
    renderConversationMode();
  }
}

async function greetLocalConversation(generation) {
  const greeting = new AbortController();
  conversationRequest = greeting;
  try {
    setConversationPhase('thinking', `${conversationSpeakerName()} begrüßt dich …`);
    await localConversation.greet(greeting.signal);
  } finally {
    if (conversationRequest === greeting) conversationRequest = null;
  }
}

async function startConversation({ skipIntro = false } = {}) {
  // An older asynchronous stop must finish before it can touch a new session.
  await conversationStopping;
  if (conversationActive || conversationReturning || conversationMotionId) return;
  conversationRecoveredId = null;
  conversationActive = true;
  localTaskNotice = false;
  conversationSpeechDetected = false;
  realtimeTaskCalls.clear();
  realtimeTaskFeedback.reset();
  realtimeTaskLastState = null;
  conversationTaskFeedback.hidden = false;
  conversationTaskFeedback.textContent = 'Noch kein Roboterauftrag gestartet.';
  realtimeTaskActive = false;
  realtimeTaskEverStarted = false;
  realtimeMolmoPreloadWarning = '';
  realtimeSpeechGripperAvailable = true;
  conversationVoiceOnly = false;
  const generation = ++conversationGeneration;
  setConversationPhase('connecting', 'Mikrofon wird verbunden …');
  try {
    conversationAudioContext = new AudioContext();
    await conversationAudioContext.resume();
    if (conversationAudioContext.state !== 'running') throw new Error('Audioeingang ist im Browser angehalten.');
    if (!conversationActive || generation !== conversationGeneration) return;
    if (conversationMode === 'realtime') {
      const readiness = await readJson(await fetch('/api/conversation/status?mode=realtime', { cache: 'no-store' }));
      if (conversationLanguage === 'English' && !readiness.conversationLanguages?.includes('English')) {
        throw new Error('Englische Gespräche erfordern einen Backend-Neustart.');
      }
      if (readiness.followerPortAvailable !== false && readiness.realtimeTaskProtocol !== 4) {
        throw new Error('Der laufende Server unterstützt die aktuelle Robotersteuerung noch nicht. Bitte Backend neu starten.');
      }
      if (!conversationActive || generation !== conversationGeneration) return;
    }
    if (conversationMode !== 'realtime') {
      const readiness = await readJson(await fetch(`/api/conversation/status?mode=${conversationMode}`, { cache: 'no-store' }));
      if (conversationLanguage === 'English' && !readiness.conversationLanguages?.includes('English')) {
        throw new Error('Englische Gespräche erfordern einen Backend-Neustart.');
      }
      if (readiness.localTaskProtocol !== 1 || (conversationMode === 'local' && !readiness.localTtsEngines?.includes('qwen'))) throw new Error('Lokale Roboterwerkzeuge erfordern ein Backend-Update.');
    }
    // All conversation voices use live audio. Never play the recorded intro
    // welcome; local TTS generates its own opening once the intro is held.
    const started = await postConversationMotion('start', { skipIntro, realtimeIntro: true });
    conversationVoiceOnly = started.status === 'voice-only';
    conversationMotionId = conversationVoiceOnly ? null : started.sessionId;
    if (!conversationVoiceOnly && !conversationMotionId) throw new Error('Gesprächsbewegung hat keine Sitzungs-ID geliefert.');
    if (conversationMotionId) sessionStorage.setItem('so101-conversation-motion-id', conversationMotionId);
    if (!conversationActive || generation !== conversationGeneration) {
      await stopConversationMotion();
      return;
    }
    if (conversationMotionId) {
      conversationHeartbeat = setInterval(() => {
        void postConversationMotion('heartbeat', { sessionId: conversationMotionId })
        .catch((error) => {
          if (!conversationActive) return;
          setConversationPhase('error', `Follower-Verbindung: ${error.message}`);
          endConversation(true);
        });
      }, 5000);
      if (conversationMode !== 'realtime') await waitForConversationIntro(generation);
    } else {
      setConversationPhase('connecting', 'Ohne SO-101 · Mikrofon wird geöffnet …');
    }
    if (!conversationActive || generation !== conversationGeneration) return;
    const media = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    if (!conversationActive || generation !== conversationGeneration) {
      media.getTracks().forEach((track) => track.stop());
      return;
    }
    conversationStream = media;
    media.getAudioTracks().forEach((track) => track.addEventListener('ended', () => {
      if (!conversationActive || generation !== conversationGeneration) return;
      setConversationPhase('error', 'Mikrofonverbindung wurde getrennt.');
      endConversation(true);
    }));
    if (conversationMode === 'realtime') {
      setConversationPhase('connecting', 'ChatGPT Realtime wird verbunden …');
      await startRealtimeSession(media, generation);
      if (!conversationActive || generation !== conversationGeneration) return;
      if (conversationMotionId) {
        await waitForConversationIntro(generation, { quiet: true });
        if (!conversationActive || generation !== conversationGeneration) return;
        // Voice is already connected. Optional policy warmup must not delay it.
        if (!realtimeTaskActive) void preloadRealtimeMolmo(conversationMotionId).then(preload => {
          if (!conversationActive || generation !== conversationGeneration) return;
          if (!preload.ready) realtimeMolmoPreloadWarning = `MolmoAct2 wurde nicht vorgeladen: ${preload.reason}`;
        });
      }
    } else {
      const source = conversationAudioContext.createMediaStreamSource(media);
      conversationAnalyser = conversationAudioContext.createAnalyser();
      conversationAnalyser.fftSize = 1024;
      source.connect(conversationAnalyser);
      const silentOutput = conversationAudioContext.createGain();
      silentOutput.gain.value = 0;
      conversationAnalyser.connect(silentOutput);
      silentOutput.connect(conversationAudioContext.destination);
      const connected = await localConversation.start(conversationMotionId);
      if (!connected || !conversationActive || generation !== conversationGeneration) return;
      realtimeTaskPoll = setInterval(() => { void pollLocalTask(generation); }, 750);
      if (conversationMotionId) void preloadRealtimeMolmo(conversationMotionId).then(preload => {
        if (!conversationActive || generation !== conversationGeneration || preload.ready) return;
        conversationTaskFeedback.textContent = `MolmoAct2 wurde nicht vorgeladen: ${preload.reason}`;
      });
      render();
      await greetLocalConversation(generation);
      if (!conversationActive || generation !== conversationGeneration) return;
      listenForConversation(generation);
    }
  } catch (error) {
    if (!conversationActive || generation !== conversationGeneration) return;
    setConversationPhase('error', `Gespräch nicht verfügbar: ${error.message}`);
    void endConversation(true);
  }
}

async function stopConversationTask() {
  if (molmoRunStopState(status.taskRun, conversationTaskStopPending).disabled) return;
  conversationTaskStopPending = true;
  renderConversationTaskStop();
  try {
    const result = await readJson(await fetch('/api/task/stop', {
      method: 'POST', headers: { 'X-SO101-Stop': 'operator-click' },
    }));
    status.taskRun = result.taskRun;
    conversationTaskFeedback.hidden = false;
    conversationTaskFeedback.textContent = 'Run wird gestoppt · Modell bleibt geladen, Gespräch bleibt verbunden.';
    await refreshStatus();
  } catch (error) {
    conversationTaskFeedback.hidden = false;
    conversationTaskFeedback.textContent = `Model Run Stopp: ${error.message}`;
  } finally {
    conversationTaskStopPending = false;
    renderConversationTaskStop();
  }
}

async function stopLocalConversationTask() {
  if (molmoRunStopState(status.taskRun, conversationTaskStopPending).disabled) return;
  const generation = conversationGeneration;
  stopConversationRecording();
  conversationRequest?.abort();
  conversationRequest = null;
  // Revoke pending dialogue without delaying the physical stop behind it.
  const cancelled = localConversation.cancelTurn().catch(error => {
    conversationTaskFeedback.hidden = false;
    conversationTaskFeedback.textContent = `Lokaler Gesprächsschritt: ${error.message}`;
  });
  await stopConversationTask();
  await cancelled;
  if (conversationActive && generation === conversationGeneration && !conversationRestartPending) listenForConversation(generation);
}

conversationTaskStop.addEventListener('click', () => {
  if (conversationMode !== 'realtime') void stopLocalConversationTask();
  else void stopConversationTask();
});

function showCameraFrames(payload, modelId) {
  if (modelId !== currentCameraModel()) return;
  cameraPreviewModelId = modelId;
  const sources = payload.cameraSources || {};
  const singleMolmoCamera = modelId === 'molmoact2' &&
    ['cam0', 'cam1'].includes(sources.cam0) && sources.cam0 === sources.cam1;
  const conversationOnly = modelId === 'conversation';
  const roles = ['cam0', 'cam1'];
  let labels = ['Overhead-Kamera', 'Wrist-Kamera'];
  if (conversationOnly) labels = ['Overhead-Kamera', 'Insta360 X5'];
  if (modelId === 'molmoact2') {
    labels = sources.cam0 === 'cam0' && singleMolmoCamera
      ? ['Overhead-Kamera', 'Overhead-Ersatzbild für Insta360 X5']
      : singleMolmoCamera
        ? ['Insta360-X5-Ersatzbild für Overhead', 'Insta360 X5']
        : ['Overhead-Kamera', 'Insta360 X5'];
  }
  roles.forEach((role, index) => {
    const frame = (conversationOnly ? payload.observerPreviews : payload.previews)?.[role];
    const source = sources[role] || role;
    cameraFrameReady[index] = Boolean(frame?.jpeg) && !(singleMolmoCamera && source !== role);
    if (!frame?.jpeg && conversationOnly) {
      cameraImages[index].removeAttribute('src');
      brightnessControls[index].receive(null, null);
      exposureControls[index].receive(null, null);
      return;
    }
    if (!frame?.jpeg) throw new Error(`Bild ${role} fehlt.`);
    cameraImages[index].src = `data:image/jpeg;base64,${frame.jpeg}`;
    cameraImages[index].alt = labels[index];
    document.querySelector(`#camera-label-${index + 1}`).textContent = labels[index];
    brightnessControls[index].receive(payload.cameraBrightness?.[source], source);
    exposureControls[index].receive(payload.cameraExposure?.[source], source);
    const cameraLabel = source === 'cam1' ? 'Insta360' : source === 'wrist' ? 'Wrist-Kamera' : 'Overhead-Kamera';
    cameraSettings[index].button.setAttribute('aria-label', `Einstellungen für ${cameraLabel} · Kamera ${index + 1}`);
    document.querySelector(`#camera-settings-heading-${index + 1}`).textContent = `${cameraLabel} · Einstellungen`;
  });
  showWristObserver(payload, modelId);
  cameraStatus.textContent = conversationOnly
    ? (Object.keys(payload.observerPreviews || {}).length ? 'Live-Kameras' : 'Keine Kamera verfügbar. Kameraverbindungen prüfen.')
    : singleMolmoCamera
    ? `MolmoAct2: Ein-Kamera-Modus · ${sources.cam0 === 'cam0' ? 'Overhead' : 'Insta360 X5'} liefert cam0 und cam1 (gleiches frisches Bild)`
    : `${modelId.toUpperCase()}: frische Livebilder · ${payload.geometry}`;
  if (activeView === 'conversation' && ['molmoact2', 'conversation'].includes(modelId) && payload.observerStatus?.wrist && !wristObserverReady) {
    cameraStatus.textContent += ` · ${payload.observerStatus.wrist.message || 'Wrist-Bild derzeit nicht bereit.'}`;
  }
  conversationCameraStatus.textContent = cameraStatus.textContent;
  insta360Controls.receive(['molmoact2', 'conversation'].includes(modelId) &&
    (conversationOnly ? payload.observerPreviews?.cam1 : Object.values(sources).includes('cam1'))
    ? payload.insta360View : null);
  render();
}

function showWristObserver(payload, modelId) {
  const frame = ['molmoact2', 'conversation'].includes(modelId) ? payload.observerPreviews?.wrist : null;
  wristObserverReady = Boolean(frame?.jpeg);
  if (wristObserverReady) {
    cameraImages[2].src = `data:image/jpeg;base64,${frame.jpeg}`;
    brightnessControls[2].receive(payload.cameraBrightness?.wrist, 'wrist');
    exposureControls[2].receive(payload.cameraExposure?.wrist, 'wrist');
  } else {
    cameraImages[2].removeAttribute('src');
    brightnessControls[2].receive(null, null);
    exposureControls[2].receive(null, null);
  }
  renderWristObserver();
}

function renderWristObserver() {
  const visible = activeView === 'conversation' && (wristObserverReady || !document.querySelector('#face-tracking').hidden);
  wristObserverFigure.hidden = !visible;
  cameraImages.slice(0, 2).forEach((image, index) => {
    image.closest('figure').hidden = activeView === 'conversation' && !cameraFrameReady[index];
  });
  const count = activeView === 'conversation' ? cameraFrameReady.filter(Boolean).length + Number(visible) : 2;
  cameraViews.classList.toggle('camera-views--three', count === 3);
  cameraViews.classList.toggle('camera-views--one', count === 1);
}

async function applyCameraBrightness(role, value, controls) {
  if (controls.apply.disabled) return;
  const modelId = cameraPreviewModelId;
  const generation = ++cameraGeneration;
  cameraOpening = true;
  render();
  controls.message.textContent = 'Helligkeit wird aktualisiert …';
  try {
    const response = await fetch(`/api/cameras/${modelId}/${role}/brightness`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value }),
    });
    if (response.status === 404) throw new Error('Diese Funktion benötigt einen Neustart des aktualisierten Backends.');
    const payload = await readJson(response);
    if (generation !== cameraGeneration || modelId !== currentCameraModel()) return;
    showCameraFrames(payload, modelId);
    brightnessControls.forEach((control) => {
      if (control.role === role) control.receive(payload.cameraBrightness?.[role], role, true);
    });
    setFeedback('Kamerahelligkeit gespeichert.');
  } catch (error) {
    if (generation === cameraGeneration) {
      controls.message.textContent = `Helligkeit nicht gespeichert: ${error.message}`;
      setFeedback(`Kamerahelligkeit: ${error.message}`, 'error');
    }
  } finally {
    if (generation === cameraGeneration) cameraOpening = false;
    await refreshStatus();
  }
}

async function applyCameraExposure(role, value, controls) {
  if (controls.apply.disabled) return;
  const modelId = cameraPreviewModelId;
  const generation = ++cameraGeneration;
  cameraOpening = true;
  render();
  controls.message.textContent = 'Belichtung wird aktualisiert …';
  try {
    const response = await fetch(`/api/cameras/${modelId}/${role}/exposure`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value }),
    });
    if (response.status === 404) throw new Error('Diese Funktion benötigt einen Neustart des aktualisierten Backends.');
    const payload = await readJson(response);
    if (generation !== cameraGeneration || modelId !== currentCameraModel()) return;
    showCameraFrames(payload, modelId);
    exposureControls.forEach((control) => {
      if (control.role === role) control.receive(payload.cameraExposure?.[role], role, true);
    });
    setFeedback('Kamerabelichtung gespeichert.');
  } catch (error) {
    if (generation === cameraGeneration) {
      controls.message.textContent = `Belichtung nicht gespeichert: ${error.message}`;
      setFeedback(`Kamerabelichtung: ${error.message}`, 'error');
    }
  } finally {
    if (generation === cameraGeneration) cameraOpening = false;
    await refreshStatus();
  }
}

async function applyInsta360View(view) {
  if (insta360Controls.apply.disabled) return;
  const modelId = cameraPreviewModelId;
  const generation = ++cameraGeneration;
  cameraOpening = true;
  render();
  insta360Controls.message.textContent = 'Insta360-Ausschnitt wird aktualisiert …';
  try {
    const response = await fetch(`/api/cameras/${modelId}/insta360-view`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(view),
    });
    if (response.status === 404) throw new Error('Diese Funktion benötigt einen Neustart des aktualisierten Backends.');
    const payload = await readJson(response);
    if (generation !== cameraGeneration || modelId !== currentCameraModel()) return;
    showCameraFrames(payload, modelId);
    insta360Controls.receive(payload.insta360View, true);
    setFeedback('Insta360-Ausschnitt gespeichert.');
  } catch (error) {
    if (generation === cameraGeneration) {
      insta360Controls.message.textContent = `Ausschnitt nicht gespeichert: ${error.message}`;
      setFeedback(`Insta360: ${error.message}`, 'error');
    }
  } finally {
    if (generation === cameraGeneration) cameraOpening = false;
    await refreshStatus();
  }
}

async function ensureConversationCameras() {
  if (activeView !== 'conversation' || cameraOpening) return;
  if (status.cameraModel) {
    await refreshVisibleCameraPreview();
    return;
  }
  const modelId = status.modelSession === 'molmoact2' ? 'molmoact2' : 'conversation';
  const generation = cameraGeneration;
  cameraOpening = true;
  conversationCameraStatus.textContent = 'Kameras werden geladen …';
  render();
  try {
    const payload = await readJson(await fetch(`/api/cameras/${modelId}/select`, { method: 'POST' }));
    if (generation !== cameraGeneration || activeView !== 'conversation') return;
    status.cameraModel = modelId;
    showCameraFrames(payload, modelId);
    cameraReady = true;
  } catch (error) {
    if (generation === cameraGeneration && activeView === 'conversation') {
      conversationCameraStatus.textContent = `Kameras nicht bereit: ${error.message}`;
    }
  } finally {
    cameraOpening = false;
    render();
  }
}

async function refreshVisibleCameraPreview() {
  // Camera readiness drives automatic tracking, even with settings hidden.
  const modelId = currentCameraModel();
  const generation = cameraGeneration;
  if (activeView === 'conversation' && !status.cameraModel && !conversationEntryPending && phase === 'idle') {
    await ensureConversationCameras();
    return;
  }
  const hasCamera = activeView === 'conversation' ? Boolean(status.cameraModel)
    : cameraReady || status.cameraModel === modelId;
  if (!modelId || cameraOpening || !hasCamera || phase !== 'idle') return;
  try {
    const payload = await readJson(await fetch(`/api/cameras/${modelId}/preview`, { cache: 'no-store' }));
    if (generation !== cameraGeneration || modelId !== currentCameraModel()) return;
    showCameraFrames(payload, modelId);
    cameraReady = true;
    render();
  } catch (error) {
    if (generation === cameraGeneration && modelId === currentCameraModel()) {
      cameraReady = false;
      cameraStatus.textContent = `Kamera nicht bereit: ${error.message}`;
      conversationCameraStatus.textContent = cameraStatus.textContent;
      render();
    }
  }
}

async function pollCameraPreview() {
  await refreshVisibleCameraPreview();
  setTimeout(pollCameraPreview, 2_000);
}

function setStatusItem(element, label, kind) {
  element.className = `system-status__item system-status__item--${kind}`;
  element.lastElementChild.textContent = label;
}

function setFeedback(message, kind = 'info') {
  conversationTorqueFeedback.hidden = false;
  conversationTorqueFeedback.textContent = message;
  conversationTorqueFeedback.dataset.state = kind;
}

function render() {
  faceTracking.setContext({ view: activeView, mode: conversationMode, cameraReady,
    settingsOpen: conversationSettings.open,
    connected: conversationMode !== 'realtime' ? Boolean(localConversation.sessionId) : realtimeChannel?.readyState === 'open', active: conversationActive,
    sessionId: conversationMotionId, voiceOnly: conversationVoiceOnly,
    introComplete: Boolean(conversationMotionId && conversationIntroCompletedId === conversationMotionId),
    taskEverStarted: realtimeTaskEverStarted,
    taskActive: realtimeTaskActive, taskState: status.taskRun?.state,
    returning: conversationReturning, stopping: conversationPhase === 'error' || conversationTaskStopPending,
  });
  renderConversationSettings();
  renderConversationTaskStop();
  const taskRunning = status.taskRun?.state === 'running';
  const taskStopping = status.taskRun?.state === 'stopping';
  const teleop = status.teleoperation || {};
  const camerasAvailable = cameraReady && cameraPreviewModelId === currentCameraModel() &&
    (activeView !== 'conversation' || cameraFrameReady.some(Boolean) || wristObserverReady);
  liveCameraPanel.hidden = !camerasAvailable;
  const cameraSettingsBusy = !camerasAvailable || !backendReady || cameraOpening || conversationEntryPending || phase !== 'idle' ||
    ['loading', 'running', 'stopping'].includes(status.taskRun?.state) ||
    status.resetRunning || status.returnRunning || teleop.occupied || conversationReturning || (activeView !== 'conversation' && Boolean(conversationMotionId));
  cameraSettings.forEach((settings, index) => settings.render(camerasAvailable && (index < 2
    ? activeView !== 'conversation' || cameraFrameReady[index]
    : activeView === 'conversation' && wristObserverReady)));
  brightnessControls.forEach((controls) => controls.render(cameraSettingsBusy));
  exposureControls.forEach((controls) => controls.render(cameraSettingsBusy));
  insta360Controls.render(camerasAvailable && ['molmoact2', 'conversation'].includes(currentCameraModel()), cameraSettingsBusy);
  setStatusItem(asrStatus,
    status.asrReady ? 'ASR bereit' : status.asrLoading ? 'Qwen wird geladen' : 'ASR nicht bereit',
    status.asrReady ? 'ready' : 'muted');
  const resetInProgress = phase === 'resetting' || status.resetRunning;
  setStatusItem(robotStatus,
    resetInProgress ? 'Reset läuft' : teleop.occupied ? 'Teleoperation läuft' : taskRunning ? 'Aufgabe läuft' : status.resetHolding ? 'Position gehalten' : status.torqueHolding ? 'Torque an' : status.robotConnected ? 'Roboter verbunden' : 'Roboter getrennt',
    resetInProgress || status.robotConnected ? 'ready' : 'muted');
  cameraReload.disabled = !backendReady || cameraOpening || conversationEntryPending || phase !== 'idle' ||
    taskRunning || taskStopping || status.resetRunning ||
    conversationReturning;
  modelUnload.hidden = activeView !== 'conversation' && !status.modelSession && phase !== 'unloading';
  modelUnload.disabled = !status.modelSession || phase !== 'idle' ||
    ['loading', 'running', 'stopping'].includes(status.taskRun?.state) || status.resetRunning ||
    conversationEntryPending || conversationReturning || conversationRestartPending;
  modelUnload.textContent = phase === 'unloading' ? 'Modell wird entladen …' : 'Modell entladen';
  const canStopPhysicalRun = status.resetHolding && status.torqueAction === 'off' && (phase === 'inferring' || taskRunning);
  torqueOnButton.disabled = !status.torqueAvailable || teleop.occupied || status.torqueAction !== 'on' || status.resetRunning || status.torqueRunning || phase !== 'idle';
  torqueOffButton.disabled = !backendReady || status.resetRunning || status.torqueRunning ||
    (phase !== 'idle' && !canStopPhysicalRun && !teleop.occupied);
  teleopStartButton.disabled = !backendReady || !teleop.available || phase !== 'idle';
  teleopStopButton.disabled = !backendReady || !teleop.occupied || phase === 'teleop-stopping';
  teleopStatus.textContent = teleop.occupied ? teleop.message || 'Teleoperation läuft.'
    : teleop.state === 'failed' ? `Letzter Lauf: ${teleop.message || 'Fehler; Hardware prüfen.'}`
    : teleop.blocker || teleop.message || 'Teleoperation bereit.';
  torqueOnButton.classList.toggle('torque-button--holding', status.resetHolding || status.torqueHolding);
}

async function readJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || payload.message || `HTTP ${response.status}`);
  return payload;
}

async function refreshStatus() {
  try {
    const next = await readJson(await fetch('/api/status', { cache: 'no-store' }));
    backendReady = true;
    status = {
      asrReady: Boolean(next.asrReady),
      asrLoading: Boolean(next.asrLoading),
      robotConnected: Boolean(next.robotConnected),
      modelSession: typeof next.modelSession === 'string' ? next.modelSession : null,
      cameraModel: typeof next.cameraModel === 'string' ? next.cameraModel : null,
      resetAvailable: Boolean(next.resetAvailable),
      resetRunning: Boolean(next.resetRunning),
      resetHolding: Boolean(next.resetHolding),
      returnAvailable: Boolean(next.returnAvailable),
      returnRunning: Boolean(next.returnRunning),
      returnMessage: String(next.returnMessage || ''),
      physicalReady: Boolean(next.physicalReady),
      torqueAction: next.torqueAction === 'on' ? 'on' : 'off',
      torqueAvailable: Boolean(next.torqueAvailable),
      torqueRunning: Boolean(next.torqueRunning),
      torqueHolding: Boolean(next.torqueHolding),
      torqueMessage: String(next.torqueMessage || ''),
      teleoperation: next.teleoperation && typeof next.teleoperation === 'object'
        ? next.teleoperation : { state: 'idle', occupied: false, available: false, blocker: '', message: 'Teleoperation im Backend noch nicht verfügbar.' },
      taskRun: next.taskRun && typeof next.taskRun === 'object' ? next.taskRun : null,
      message: String(next.message || ''),
    };
  } catch {
    backendReady = false;
    status = { asrReady: false, asrLoading: false, robotConnected: false, modelSession: null, cameraModel: null, resetAvailable: false, resetRunning: false, returnAvailable: false, returnRunning: false, returnMessage: '', physicalReady: false, torqueAction: 'off', torqueAvailable: false, torqueRunning: false, torqueHolding: false, torqueMessage: '', teleoperation: { state: 'idle', occupied: false, available: false, blocker: '', message: 'Lokaler Dienst nicht erreichbar.' }, taskRun: null, message: '' };
    setFeedback('Lokaler Dienst nicht erreichbar. Bitte Backend starten.', 'error');
  }
  render();
}

function preferredMimeType() {
  if (!window.MediaRecorder) return null;
  return ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus']
    .find((type) => MediaRecorder.isTypeSupported(type)) || '';
}

function setModelUnloadFeedback(message, kind = 'info') {
  setFeedback(message, kind);
  if (activeView !== 'conversation') return;
  conversationTaskFeedback.hidden = false;
  conversationTaskFeedback.textContent = message;
}

async function unloadModel() {
  if (!status.modelSession || ['loading', 'running', 'stopping'].includes(status.taskRun?.state) ||
      status.resetRunning || phase !== 'idle' || conversationEntryPending ||
      conversationReturning || conversationRestartPending) return;
  phase = 'unloading';
  render();
  setModelUnloadFeedback('Geladenes Modell wird entladen; Live-Kameras bleiben aktiv …');
  try {
    await readJson(await fetch('/api/models/current', { method: 'DELETE' }));
    status.modelSession = null;
    modelManuallyUnloaded = true;
    sessionStorage.setItem('so101-model-manually-unloaded', '1');
    setModelUnloadFeedback('Modell entladen. Live-Kameras bleiben aktiv.');
  } catch (error) {
    setModelUnloadFeedback(`Modell konnte nicht entladen werden: ${error.message}`, 'error');
  } finally {
    phase = 'idle';
    await refreshStatus();
  }
}
modelUnload.addEventListener('click', unloadModel);

cameraReload.addEventListener('click', async () => {
  if (cameraReload.disabled) return;
  const modelId = currentCameraModel();
  const generation = ++cameraGeneration;
  cameraReady = false;
  cameraOpening = true;
  cameraStatus.textContent = 'Live-Kameras werden neu geladen …';
  cameraImages.forEach((image) => image.removeAttribute('src'));
  render();
  try {
    const response = await fetch(`/api/cameras/${modelId}/reload`, { method: 'POST' });
    // An already running backend may not have the dedicated reload route yet.
    const previewOnly = response.status === 404;
    const payload = await readJson(previewOnly
      ? await fetch(`/api/cameras/${modelId}/select`, { method: 'POST' })
      : response);
    if (generation !== cameraGeneration || modelId !== currentCameraModel()) return;
    showCameraFrames(payload, modelId);
    cameraReady = true;
    setFeedback(previewOnly ? 'Live-Kamerabilder aktualisiert.' : 'Live-Kameras neu geladen.');
  } catch (error) {
    if (generation === cameraGeneration) {
      cameraStatus.textContent = `Kamera nicht bereit: ${error.message}`;
      setFeedback(`Kameras konnten nicht neu geladen werden: ${error.message}`, 'error');
    }
  } finally {
    if (generation === cameraGeneration) cameraOpening = false;
    await refreshStatus();
  }
});

function setTorqueFeedback(message, kind = 'info') {
  setFeedback(message, kind);
  conversationTorqueFeedback.hidden = false;
  conversationTorqueFeedback.textContent = message;
  conversationTorqueFeedback.dataset.state = kind;
}

async function setTorque(turningOn) {
  if (!backendReady || status.resetRunning || status.torqueRunning ||
      (turningOn && (!status.torqueAvailable || status.torqueAction !== 'on' || phase !== 'idle')) ||
      (!turningOn && phase !== 'idle' &&
       !(phase === 'inferring' && status.resetHolding && status.torqueAction === 'off') &&
       !status.teleoperation?.occupied)) return;
  if (!turningOn && status.teleoperation?.occupied) teleopActionGeneration += 1;
  phase = turningOn ? 'torque-on' : 'releasing';
  render();
  setTorqueFeedback(turningOn ? 'Aktuelle Position wird eingelesen; Drehmoment wird eingeschaltet …' : 'Drehmoment wird ausgeschaltet und geprüft …');
  try {
    const resetRelease = !turningOn && status.resetHolding;
    const result = await readJson(await fetch(resetRelease ? '/api/reset/release' : `/api/torque/${turningOn ? 'on' : 'off'}`, {
      method: 'POST',
      headers: resetRelease ? { 'X-SO101-Reset': 'operator-click' } : { 'X-SO101-Torque': 'operator-click' },
    }));
    setTorqueFeedback(result.message || (turningOn ? 'Torque an.' : 'Torque Aus.'));
  } catch (error) {
    setTorqueFeedback(`Drehmoment konnte nicht ${turningOn ? 'eingeschaltet' : 'ausgeschaltet'} werden: ${error.message}`, 'error');
  } finally {
    phase = 'idle';
    await refreshStatus();
  }
}

torqueOnButton.addEventListener('click', () => { void setTorque(true); });
torqueOffButton.addEventListener('click', () => { void setTorque(false); });

async function setTeleoperation(starting) {
  if ((starting ? teleopStartButton : teleopStopButton).disabled) return;
  const generation = ++teleopActionGeneration;
  phase = starting ? 'teleop-starting' : 'teleop-stopping';
  render();
  setFeedback(starting ? 'Leader und Follower werden geprüft; Teleoperation startet …'
    : 'Teleoperation stoppt; gemessener Follower-Halt wird geprüft …');
  try {
    const result = await readJson(await fetch(`/api/teleoperation/${starting ? 'start' : 'stop'}`, {
      method: 'POST', headers: { 'X-SO101-Teleop': 'operator-click' },
    }));
    if (generation === teleopActionGeneration) setFeedback(result.message || 'Teleoperation aktualisiert.');
  } catch (error) {
    if (generation === teleopActionGeneration) setFeedback(`Teleoperation: ${error.message}`, 'error');
  } finally {
    if (generation === teleopActionGeneration) {
      phase = 'idle';
      await refreshStatus();
    }
  }
}

teleopStartButton.addEventListener('click', () => { void setTeleoperation(true); });
teleopStopButton.addEventListener('click', () => { void setTeleoperation(false); });

render();
async function pollStatus() {
  await refreshStatus();
  if (backendReady && !conversationEntryReady && !conversationEntryPending) await initializeConversation();
  setTimeout(pollStatus, status.asrLoading || status.teleoperation?.occupied ||
    ['running', 'stopping'].includes(status.taskRun?.state) ? 2_000 : 10_000);
}
void pollStatus();
void pollCameraPreview();
