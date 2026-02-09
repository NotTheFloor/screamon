// Screamon Dashboard — Alpine.js Component

const API_BASE = '/api';

function dashboard() {
    return {
        detectors: [],
        events: [],
        config: { refresh_rate: 3 },
        esi: { configured: false, characters: [] },
        blueprints: [],
        showDistinct: false,
        expandedBp: null,
        materialPrices: {},
        loadingPrices: false,
        esiMessage: '',
        loading: { detectors: true, events: true, esi: true, blueprints: false },

        init() {
            this.loadDetectors();
            this.loadConfig();
            this.loadEvents();
            this.loadESIStatus();

            setInterval(() => {
                this.loadDetectors();
                this.loadEvents();
            }, 2000);

            setInterval(() => this.loadESIStatus(), 10000);
        },

        // API helper
        async fetchAPI(endpoint, options = {}) {
            const response = await fetch(`${API_BASE}${endpoint}`, {
                headers: { 'Content-Type': 'application/json' },
                ...options,
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json();
        },

        // Data loaders
        async loadDetectors() {
            try {
                this.detectors = await this.fetchAPI('/detectors/');
            } catch (e) {
                console.error('Failed to load detectors', e);
            } finally {
                this.loading.detectors = false;
            }
        },

        async loadConfig() {
            try {
                this.config = await this.fetchAPI('/config');
            } catch (e) {
                console.error('Failed to load config', e);
            }
        },

        async loadEvents() {
            try {
                this.events = await this.fetchAPI('/events/?limit=20');
            } catch (e) {
                console.error('Failed to load events', e);
            } finally {
                this.loading.events = false;
            }
        },

        async loadESIStatus() {
            try {
                const response = await fetch('/esi/status');
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const data = await response.json();
                this.esi = {
                    configured: data.configured,
                    characters: data.characters || [],
                };
            } catch (e) {
                console.error('Failed to load ESI status', e);
            } finally {
                this.loading.esi = false;
            }
        },

        async loadBlueprints() {
            this.loading.blueprints = true;
            try {
                this.blueprints = await this.fetchAPI('/esi/data/blueprints');
            } catch (e) {
                console.error('Failed to load blueprints', e);
            } finally {
                this.loading.blueprints = false;
            }
        },

        get filteredBlueprints() {
            if (!this.showDistinct) return this.blueprints;
            const seen = new Map();
            for (const bp of this.blueprints) {
                const key = bp.type_id;
                if (seen.has(key)) {
                    seen.get(key).count++;
                } else {
                    seen.set(key, { ...bp, count: 1 });
                }
            }
            return Array.from(seen.values());
        },

        // Actions
        async toggleDetector(name) {
            try {
                await this.fetchAPI(`/detectors/${name}/toggle`, { method: 'POST' });
                await this.loadDetectors();
            } catch (e) {
                alert(`Failed to toggle detector: ${e.message}`);
            }
        },

        async calibrateDetector(name) {
            try {
                const result = await this.fetchAPI(`/detectors/${name}/calibrate`, { method: 'POST' });
                alert(result.message);
            } catch (e) {
                alert(`Failed to request calibration: ${e.message}`);
            }
        },

        async saveConfig() {
            try {
                await this.fetchAPI('/config', {
                    method: 'PUT',
                    body: JSON.stringify({ refresh_rate: parseFloat(this.config.refresh_rate) }),
                });
                alert('Configuration saved!');
            } catch (e) {
                alert(`Failed to save config: ${e.message}`);
            }
        },

        async esiLogin() {
            try {
                const response = await fetch('/esi/login');
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                this.esiMessage = 'Opening EVE login... If nothing happened, check your browser.';
            } catch (e) {
                alert(`Failed to start ESI login: ${e.message}`);
            }
        },

        async esiActivateCharacter(characterId) {
            try {
                await fetch(`/api/esi/characters/${characterId}/activate`, { method: 'POST' });
                await this.loadESIStatus();
            } catch (e) {
                alert(`Failed to activate character: ${e.message}`);
            }
        },

        async esiRemoveCharacter(characterId) {
            if (!confirm('Remove this character?')) return;
            try {
                await fetch(`/api/esi/characters/${characterId}`, { method: 'DELETE' });
                await this.loadESIStatus();
            } catch (e) {
                alert(`Failed to remove character: ${e.message}`);
            }
        },

        // Formatters
        formatDetectorName(name) {
            return name
                .split('_')
                .map(w => w.charAt(0).toUpperCase() + w.slice(1))
                .join(' ');
        },

        formatTime(isoString) {
            const date = new Date(isoString);
            const now = new Date();
            const diff = now - date;

            if (diff < 60000) return 'Just now';
            if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
            if (date.toDateString() === now.toDateString()) {
                return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            }
            return date.toLocaleDateString([], {
                month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
            });
        },

        eventValueChange(event) {
            return event.old_value !== null
                ? `${event.old_value} → ${event.new_value}`
                : event.new_value;
        },

        bpLabel(bp) {
            if (bp.copy) return 'BPC';
            if (bp.quantity > 0) return `BPO x${bp.quantity}`;
            return 'BPO';
        },

        bpRuns(bp) {
            return bp.runs === -1 ? '∞' : bp.runs;
        },

        async toggleBpMaterials(bp) {
            const key = this.showDistinct ? bp.type_id : bp.item_id;
            if (this.expandedBp === key) {
                this.expandedBp = null;
                return;
            }
            this.expandedBp = key;

            // Fetch prices for materials if we have them
            if (bp.materials && bp.materials.length > 0) {
                const needed = bp.materials
                    .map(m => m.type_id)
                    .filter(id => !(id in this.materialPrices));
                if (needed.length > 0) {
                    this.loadingPrices = true;
                    try {
                        const data = await this.fetchAPI(
                            `/market/prices?type_ids=${needed.join(',')}`
                        );
                        Object.assign(this.materialPrices, data.prices);
                    } catch (e) {
                        console.error('Failed to load prices', e);
                    } finally {
                        this.loadingPrices = false;
                    }
                }
            }
        },

        isBpExpanded(bp) {
            const key = this.showDistinct ? bp.type_id : bp.item_id;
            return this.expandedBp === key;
        },

        matSellPrice(mat) {
            const p = this.materialPrices[mat.type_id];
            return p && p.sell != null ? p.sell : null;
        },

        matTotalCost(mat) {
            const price = this.matSellPrice(mat);
            return price != null ? price * mat.quantity : null;
        },

        bpTotalCost(bp) {
            if (!bp.materials) return null;
            let total = 0;
            for (const mat of bp.materials) {
                const cost = this.matTotalCost(mat);
                if (cost == null) return null;
                total += cost;
            }
            return total;
        },

        formatISK(value) {
            if (value == null) return '—';
            if (value >= 1e9) return (value / 1e9).toFixed(2) + 'B';
            if (value >= 1e6) return (value / 1e6).toFixed(2) + 'M';
            if (value >= 1e3) return (value / 1e3).toFixed(1) + 'K';
            return value.toFixed(2);
        },

        formatQuantity(n) {
            return n.toLocaleString();
        },
    };
}
