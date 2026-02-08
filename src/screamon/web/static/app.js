// Screamon Dashboard JavaScript

const API_BASE = '/api';

// State
let detectors = [];
let config = {};

// DOM Elements
const detectorsContainer = document.getElementById('detectors');
const eventsContainer = document.getElementById('events');
const refreshRateInput = document.getElementById('refresh-rate');
const saveConfigBtn = document.getElementById('save-config');

// ESI Elements
const esiContainer = document.getElementById('esi-status');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadDetectors();
    loadConfig();
    loadEvents();
    loadESIStatus();

    // Auto-refresh every 2 seconds
    setInterval(() => {
        loadDetectors();
        loadEvents();
    }, 2000);

    // Refresh ESI status less frequently
    setInterval(loadESIStatus, 10000);

    // Save config button
    saveConfigBtn.addEventListener('click', saveConfig);
});

// API Functions
async function fetchAPI(endpoint, options = {}) {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            headers: {
                'Content-Type': 'application/json',
            },
            ...options,
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        return await response.json();
    } catch (error) {
        console.error(`API Error: ${endpoint}`, error);
        throw error;
    }
}

async function loadDetectors() {
    try {
        detectors = await fetchAPI('/detectors/');
        renderDetectors();
    } catch (error) {
        detectorsContainer.innerHTML = '<div class="loading">Error loading detectors</div>';
    }
}

async function loadConfig() {
    try {
        config = await fetchAPI('/config');
        refreshRateInput.value = config.refresh_rate;
    } catch (error) {
        console.error('Failed to load config', error);
    }
}

async function loadEvents() {
    try {
        const events = await fetchAPI('/events/?limit=20');
        renderEvents(events);
    } catch (error) {
        eventsContainer.innerHTML = '<div class="loading">Error loading events</div>';
    }
}

async function toggleDetector(name) {
    try {
        await fetchAPI(`/detectors/${name}/toggle`, { method: 'POST' });
        loadDetectors();
    } catch (error) {
        alert(`Failed to toggle detector: ${error.message}`);
    }
}

async function calibrateDetector(name) {
    try {
        const result = await fetchAPI(`/detectors/${name}/calibrate`, { method: 'POST' });
        alert(result.message);
    } catch (error) {
        alert(`Failed to request calibration: ${error.message}`);
    }
}

async function saveConfig() {
    try {
        const data = {
            refresh_rate: parseFloat(refreshRateInput.value),
        };
        await fetchAPI('/config', {
            method: 'PUT',
            body: JSON.stringify(data),
        });
        alert('Configuration saved!');
    } catch (error) {
        alert(`Failed to save config: ${error.message}`);
    }
}

// ESI Functions
async function loadESIStatus() {
    try {
        const response = await fetch('/esi/status');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        renderESIStatus(data);
    } catch (error) {
        esiContainer.innerHTML = '<div class="loading">Error loading ESI status</div>';
    }
}

async function esiLogin() {
    try {
        const response = await fetch('/esi/login');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        // Browser should open automatically; show URL as fallback
        esiContainer.querySelector('.esi-message').textContent =
            'Opening EVE login... If nothing happened, click the link below.';
    } catch (error) {
        alert(`Failed to start ESI login: ${error.message}`);
    }
}

async function esiActivateCharacter(characterId) {
    try {
        await fetch(`/api/esi/characters/${characterId}/activate`, { method: 'POST' });
        loadESIStatus();
    } catch (error) {
        alert(`Failed to activate character: ${error.message}`);
    }
}

async function esiRemoveCharacter(characterId) {
    if (!confirm('Remove this character?')) return;
    try {
        await fetch(`/api/esi/characters/${characterId}`, { method: 'DELETE' });
        loadESIStatus();
    } catch (error) {
        alert(`Failed to remove character: ${error.message}`);
    }
}

function renderESIStatus(data) {
    if (!data.configured) {
        esiContainer.innerHTML = `
            <div class="esi-not-configured">
                <p>ESI not configured. Add <code>client_id</code> to your <code>.env</code> file.</p>
            </div>
        `;
        return;
    }

    const characters = data.characters || [];
    const characterList = characters.length > 0
        ? characters.map(c => `
            <div class="esi-character ${c.is_active ? 'active' : ''}">
                <span class="esi-character-name">${c.character_name}</span>
                ${c.is_active ? '<span class="esi-badge">Active</span>' : ''}
                <div class="esi-character-actions">
                    ${!c.is_active ? `<button class="secondary" onclick="esiActivateCharacter(${c.character_id})">Activate</button>` : ''}
                    <button class="secondary" onclick="esiRemoveCharacter(${c.character_id})">Remove</button>
                </div>
            </div>
        `).join('')
        : '<p class="esi-message">No characters authenticated yet.</p>';

    esiContainer.innerHTML = `
        <div class="esi-content">
            <div class="esi-characters">${characterList}</div>
            <button class="esi-login-btn" onclick="esiLogin()">Authenticate with EVE Online</button>
            <p class="esi-message"></p>
        </div>
    `;
}

// Render Functions
function renderDetectors() {
    if (detectors.length === 0) {
        detectorsContainer.innerHTML = '<div class="loading">No detectors configured</div>';
        return;
    }

    detectorsContainer.innerHTML = detectors.map(detector => {
        const displayName = formatDetectorName(detector.name);
        const valueDisplay = detector.value !== null
            ? `<div class="value">${detector.value}</div>`
            : `<div class="value no-data">No data</div>`;

        const lastChanged = detector.last_changed
            ? `<div class="last-changed">Changed: ${formatTime(detector.last_changed)}</div>`
            : '';

        const cardClass = detector.enabled ? '' : 'disabled';
        const coordsStatus = detector.coords_set ? 'Calibrated' : 'Not calibrated';

        return `
            <div class="detector-card ${cardClass}">
                <div class="status-indicator"></div>
                <div class="name">${displayName}</div>
                ${valueDisplay}
                ${lastChanged}
                <div class="coords-status" style="font-size: 0.8rem; color: var(--text-muted);">
                    ${coordsStatus}
                </div>
                <div class="actions">
                    <label class="toggle">
                        <input type="checkbox" ${detector.enabled ? 'checked' : ''}
                               onchange="toggleDetector('${detector.name}')">
                        <span class="slider"></span>
                        Enable
                    </label>
                    <button class="secondary" onclick="calibrateDetector('${detector.name}')">
                        Calibrate
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

function renderEvents(events) {
    if (events.length === 0) {
        eventsContainer.innerHTML = '<div class="loading">No events yet</div>';
        return;
    }

    eventsContainer.innerHTML = events.map(event => {
        const displayName = formatDetectorName(event.detector);
        const valueChange = event.old_value !== null
            ? `${event.old_value} → ${event.new_value}`
            : event.new_value;

        return `
            <div class="event-item">
                <div>
                    <span class="detector-name">${displayName}</span>
                    <span class="event-type ${event.event_type}">${event.event_type}</span>
                </div>
                <div class="event-value">${valueChange}</div>
                <div class="event-time">${formatTime(event.timestamp)}</div>
            </div>
        `;
    }).join('');
}

// Helper Functions
function formatDetectorName(name) {
    return name
        .split('_')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}

function formatTime(isoString) {
    const date = new Date(isoString);
    const now = new Date();
    const diff = now - date;

    // Less than a minute ago
    if (diff < 60000) {
        return 'Just now';
    }

    // Less than an hour ago
    if (diff < 3600000) {
        const mins = Math.floor(diff / 60000);
        return `${mins}m ago`;
    }

    // Today
    if (date.toDateString() === now.toDateString()) {
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    // Other
    return date.toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
