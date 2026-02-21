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
        showBPO: true,
        showBPC: true,
        showReactions: true,
        showInvention: false,
        sortMode: 'name',           // 'name', 'max_profit', 'min_profit'
        bulkLoading: false,
        bulkProgress: 0,
        bulkProgressLabel: '',
        expandedBp: null,
        materialPrices: {},
        bpEIVs: {},
        systemCostIndex: null,
        systemName: 'Serren',
        reactionSystemCostIndex: null,
        reactionSystemName: 'Obalyu',
        loadingPrices: false,
        esiMessage: '',
        loading: { detectors: true, events: true, esi: true, blueprints: false },

        // Facility state
        facilities: [],
        selectedFacilityId: null,
        selectedFacility: null,
        showFacilityEditor: false,
        editingFacility: null,
        facilityForm: { name: '', structure_type_id: '', system_name: '', rig1_type_id: '', rig2_type_id: '', rig3_type_id: '', facility_tax: 0 },
        structures: {},
        allRigs: {},
        facilitySystemSecurity: null,
        blueprintRigCategories: {},

        // Character skills state
        characterSkills: {},        // skill_id -> trained_skill_level
        characterSkillsLoaded: false,

        // Settings state
        salesTaxRate: 0.036,
        brokerFeeRate: 0.03,
        settingsLoaded: false,

        // Profit state
        inventionSources: {},       // t2_bp_type_id -> t1_bp_type_id

        // Invention state
        inventionMode: {},          // bp.type_id -> boolean
        inventionData: {},          // bp.type_id -> {materials, products, skills, time}
        decryptors: {},             // type_id -> {name, prob_mult, me_mod, te_mod, run_mod}
        decryptorsLoaded: false,
        selectedDecryptor: {},      // bp.type_id -> decryptor type_id or ''
        selectedT2Product: {},      // bp.type_id -> T2 product type_id
        inventionEIVs: {},          // t2_bp_type_id -> EIV value
        inventionSCI: null,         // invention system cost index

        init() {
            this.loadDetectors();
            this.loadConfig();
            this.loadEvents();
            this.loadESIStatus();
            this.loadFacilities();
            this.loadSettings();

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

        bpKind(bp) {
            if (bp.activity_type === 'reaction') return 'reaction';
            return bp.copy ? 'bpc' : 'bpo';
        },

        get filteredBlueprints() {
            // Type filter
            let list = this.blueprints.filter(bp => {
                const kind = this.bpKind(bp);
                if (kind === 'bpo' && !this.showBPO) return false;
                if (kind === 'bpc' && !this.showBPC) return false;
                if (kind === 'reaction' && !this.showReactions) return false;
                if (this.showInvention && !bp.has_invention) return false;
                return true;
            });

            if (this.showDistinct) {
                // Distinct: group by type_id + kind + ME + TE
                const seen = new Map();
                for (const bp of list) {
                    const kind = this.bpKind(bp);
                    const me = bp.material_efficiency || 0;
                    const te = bp.time_efficiency || 0;
                    const key = `${bp.type_id}:${kind}:${me}:${te}`;
                    if (seen.has(key)) {
                        seen.get(key).count++;
                    } else {
                        seen.set(key, { ...bp, _distinctKey: key, count: 1 });
                    }
                }
                list = Array.from(seen.values());
            }

            // Sort
            if (this.sortMode === 'max_profit') {
                // Best case: buy order inputs + sell order output
                list = [...list].sort((a, b) => {
                    const pa = this.bpProfit(a, 'buy', 'order');
                    const pb = this.bpProfit(b, 'buy', 'order');
                    const va = pa ? pa.profit : -Infinity;
                    const vb = pb ? pb.profit : -Infinity;
                    return vb - va;
                });
            } else if (this.sortMode === 'min_profit') {
                // Worst case: instant buy + instant sell
                list = [...list].sort((a, b) => {
                    const pa = this.bpProfit(a, 'sell', 'sell');
                    const pb = this.bpProfit(b, 'sell', 'sell');
                    const va = pa ? pa.profit : -Infinity;
                    const vb = pb ? pb.profit : -Infinity;
                    return vb - va;
                });
            }

            return list;
        },

        async loadCharacterSkills() {
            if (this.characterSkillsLoaded) return;
            try {
                const data = await this.fetchAPI('/esi/data/skills');
                const map = {};
                for (const s of data.skills || []) {
                    map[s.skill_id] = s.active_skill_level;
                }
                this.characterSkills = map;
                this.characterSkillsLoaded = true;
            } catch (e) {
                console.error('Failed to load character skills', e);
            }
        },

        // Facility data loaders
        async loadFacilities() {
            try {
                this.facilities = await this.fetchAPI('/facilities/');
            } catch (e) {
                console.error('Failed to load facilities', e);
            }
        },

        // Settings methods
        async loadSettings() {
            try {
                const data = await this.fetchAPI('/settings/');
                this.salesTaxRate = data.sales_tax_rate;
                this.brokerFeeRate = data.broker_fee_rate;
                this.settingsLoaded = true;
            } catch (e) {
                console.error('Failed to load settings', e);
            }
        },

        async saveSettings() {
            try {
                await this.fetchAPI('/settings/', {
                    method: 'PUT',
                    body: JSON.stringify({
                        sales_tax_rate: this.salesTaxRate,
                        broker_fee_rate: this.brokerFeeRate,
                    }),
                });
            } catch (e) {
                console.error('Failed to save settings', e);
            }
        },

        async loadStructures() {
            if (Object.keys(this.structures).length > 0) return;
            try {
                this.structures = await this.fetchAPI('/sde/structures');
            } catch (e) {
                console.error('Failed to load structures', e);
            }
        },

        async loadRigs() {
            if (Object.keys(this.allRigs).length > 0) return;
            try {
                this.allRigs = await this.fetchAPI('/sde/rigs');
            } catch (e) {
                console.error('Failed to load rigs', e);
            }
        },

        async selectFacility(id) {
            if (id === '' || id === null) {
                this.selectedFacilityId = null;
                this.selectedFacility = null;
                this.facilitySystemSecurity = null;
                return;
            }
            this.selectedFacilityId = parseInt(id);
            this.selectedFacility = this.facilities.find(f => f.id === this.selectedFacilityId) || null;
            if (this.selectedFacility) {
                try {
                    this.facilitySystemSecurity = await this.fetchAPI(
                        `/sde/system-security/${encodeURIComponent(this.selectedFacility.system_name)}`
                    );
                } catch (e) {
                    console.error('Failed to load system security', e);
                    this.facilitySystemSecurity = null;
                }
                // Load structures/rigs if not yet loaded (for display)
                await Promise.all([this.loadStructures(), this.loadRigs()]);
            }
        },

        // Facility CRUD
        async openFacilityEditor(facility) {
            await Promise.all([this.loadStructures(), this.loadRigs()]);
            if (facility) {
                this.editingFacility = facility;
                this.facilityForm = {
                    name: facility.name,
                    structure_type_id: String(facility.structure_type_id),
                    system_name: facility.system_name,
                    rig1_type_id: facility.rig1_type_id ? String(facility.rig1_type_id) : '',
                    rig2_type_id: facility.rig2_type_id ? String(facility.rig2_type_id) : '',
                    rig3_type_id: facility.rig3_type_id ? String(facility.rig3_type_id) : '',
                    facility_tax: facility.facility_tax * 100,
                };
            } else {
                this.editingFacility = null;
                this.facilityForm = {
                    name: '', structure_type_id: '', system_name: '',
                    rig1_type_id: '', rig2_type_id: '', rig3_type_id: '',
                    facility_tax: 0,
                };
            }
            this.showFacilityEditor = true;
        },

        closeFacilityEditor() {
            this.showFacilityEditor = false;
            this.editingFacility = null;
        },

        async saveFacility() {
            const payload = {
                name: this.facilityForm.name,
                structure_type_id: parseInt(this.facilityForm.structure_type_id),
                system_name: this.facilityForm.system_name,
                rig1_type_id: this.facilityForm.rig1_type_id ? parseInt(this.facilityForm.rig1_type_id) : null,
                rig2_type_id: this.facilityForm.rig2_type_id ? parseInt(this.facilityForm.rig2_type_id) : null,
                rig3_type_id: this.facilityForm.rig3_type_id ? parseInt(this.facilityForm.rig3_type_id) : null,
                facility_tax: parseFloat(this.facilityForm.facility_tax) / 100,
            };
            try {
                if (this.editingFacility) {
                    await this.fetchAPI(`/facilities/${this.editingFacility.id}`, {
                        method: 'PUT',
                        body: JSON.stringify(payload),
                    });
                } else {
                    await this.fetchAPI('/facilities/', {
                        method: 'POST',
                        body: JSON.stringify(payload),
                    });
                }
                await this.loadFacilities();
                this.closeFacilityEditor();
                // Re-select if editing the active facility
                if (this.selectedFacilityId) {
                    await this.selectFacility(this.selectedFacilityId);
                }
            } catch (e) {
                alert(`Failed to save facility: ${e.message}`);
            }
        },

        async deleteFacility(id) {
            if (!confirm('Delete this facility?')) return;
            try {
                await this.fetchAPI(`/facilities/${id}`, { method: 'DELETE' });
                await this.loadFacilities();
                if (this.selectedFacilityId === id) {
                    this.selectedFacilityId = null;
                    this.selectedFacility = null;
                    this.facilitySystemSecurity = null;
                }
                this.closeFacilityEditor();
            } catch (e) {
                alert(`Failed to delete facility: ${e.message}`);
            }
        },

        get filteredRigs() {
            if (!this.facilityForm.structure_type_id) return {};
            const struct = this.structures[this.facilityForm.structure_type_id];
            if (!struct) return this.allRigs;
            const size = struct.rig_size;
            const filtered = {};
            for (const [id, rig] of Object.entries(this.allRigs)) {
                if (rig.rig_size === size) {
                    filtered[id] = rig;
                }
            }
            return filtered;
        },

        // Facility bonus helpers
        getStructureMatBonus() {
            if (!this.selectedFacility) return 1.0;
            const struct = this.structures[String(this.selectedFacility.structure_type_id)];
            return struct ? struct.mat_bonus : 1.0;
        },

        getStructureCostBonus() {
            if (!this.selectedFacility) return 0;
            const struct = this.structures[String(this.selectedFacility.structure_type_id)];
            if (!struct) return 0;
            // cost_bonus is a multiplier like 0.97 meaning 3% reduction
            // We return the % reduction as a fraction (0.03)
            return 1 - struct.cost_bonus;
        },

        getApplicableRigMatBonus(bp) {
            if (!this.selectedFacility) return 1.0;
            const category = this.blueprintRigCategories[bp.type_id];
            if (!category) return 1.0;

            const rigSlots = [
                this.selectedFacility.rig1_type_id,
                this.selectedFacility.rig2_type_id,
                this.selectedFacility.rig3_type_id,
            ];

            let bestBonus = 0; // most negative = best
            for (const rigId of rigSlots) {
                if (!rigId) continue;
                const rig = this.allRigs[String(rigId)];
                if (!rig) continue;
                // Check if rig category matches blueprint product category
                if (rig.rig_category === category || rig.rig_category === 'ship') {
                    if (rig.mat_bonus < bestBonus) {
                        bestBonus = rig.mat_bonus;
                    }
                }
            }

            if (bestBonus === 0) return 1.0;

            // Apply security multiplier
            const secMult = this.facilitySystemSecurity ? this.facilitySystemSecurity.rig_multiplier : 1.0;
            // mat_bonus is negative (e.g. -2.0 for 2%), multiply by security
            return 1 + (bestBonus / 100) * secMult;
        },

        adjustedMatQuantity(bp, mat) {
            // Reactions always use ME 0
            const me = bp.activity_type === 'reaction' ? 0 : (bp.material_efficiency || 0);
            const strBonus = this.getStructureMatBonus();
            const rigBonus = this.getApplicableRigMatBonus(bp);
            const adjusted = mat.quantity * (1 - me / 100) * strBonus * rigBonus;
            return Math.max(1, Math.ceil(adjusted));
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
            if (bp.activity_type === 'reaction') return 'Formula';
            if (bp.copy) return 'BPC';
            if (bp.quantity > 0) return `BPO x${bp.quantity}`;
            return 'BPO';
        },

        bpRuns(bp) {
            return bp.runs === -1 ? '\u221e' : bp.runs;
        },

        async toggleBpMaterials(bp) {
            const key = this.showDistinct ? (bp._distinctKey || bp.type_id) : bp.item_id;
            if (this.expandedBp === key) {
                this.expandedBp = null;
                return;
            }
            this.expandedBp = key;

            // Fetch prices, EIV, and system cost index in parallel
            const promises = [];

            // Material prices + product prices
            if (bp.materials && bp.materials.length > 0) {
                const matIds = bp.materials.map(m => m.type_id);
                const productIds = (bp.products || []).map(p => p.type_id);
                const allIds = [...matIds, ...productIds];
                const needed = allIds.filter(id => !(id in this.materialPrices));
                if (needed.length > 0) {
                    promises.push(
                        this.fetchAPI(`/market/prices?type_ids=${needed.join(',')}`)
                            .then(data => Object.assign(this.materialPrices, data.prices))
                            .catch(e => console.error('Failed to load prices', e))
                    );
                }
            }

            // T2 invention source (for profit calculation)
            if (bp.is_t2 && !(bp.type_id in this.inventionSources)) {
                promises.push(
                    this.fetchAPI(`/sde/blueprints/${bp.type_id}/invention-source`)
                        .then(async (data) => {
                            const t1BpId = data.t1_blueprint_type_id;
                            this.inventionSources[bp.type_id] = t1BpId;
                            // Load T1 invention data if not already loaded
                            if (!this.inventionData[t1BpId]) {
                                const subPromises = [];
                                subPromises.push(
                                    this.fetchAPI(`/sde/blueprints/${t1BpId}/invention`)
                                        .then(invData => {
                                            this.inventionData[t1BpId] = invData;
                                            if (invData.products && invData.products.length > 0 && !this.selectedT2Product[t1BpId]) {
                                                this.selectedT2Product[t1BpId] = invData.products[0].type_id;
                                            }
                                        })
                                        .catch(e => console.error('Failed to load T1 invention data', e))
                                );
                                if (!this.characterSkillsLoaded) {
                                    subPromises.push(this.loadCharacterSkills());
                                }
                                await Promise.all(subPromises);

                                // Load invention material prices + EIV
                                const invData = this.inventionData[t1BpId];
                                if (invData) {
                                    const invPricePromises = [];
                                    const invMatIds = invData.materials
                                        .map(m => m.type_id)
                                        .filter(id => !(id in this.materialPrices));
                                    if (invMatIds.length > 0) {
                                        invPricePromises.push(
                                            this.fetchAPI(`/market/prices?type_ids=${invMatIds.join(',')}`)
                                                .then(d => Object.assign(this.materialPrices, d.prices))
                                                .catch(e => console.error('Failed to load invention prices', e))
                                        );
                                    }
                                    const t2Id = this.selectedT2Product[t1BpId];
                                    if (t2Id && !(t2Id in this.inventionEIVs)) {
                                        invPricePromises.push(
                                            this.fetchAPI(`/market/eiv/invention/${t2Id}`)
                                                .then(d => { this.inventionEIVs[t2Id] = d.eiv; })
                                                .catch(e => console.error('Failed to load invention EIV', e))
                                        );
                                    }
                                    if (this.inventionSCI === null) {
                                        invPricePromises.push(
                                            this.fetchAPI(`/market/system-cost-index?system=${encodeURIComponent(this.systemName)}&activity=invention`)
                                                .then(d => { this.inventionSCI = d.cost_index; })
                                                .catch(e => console.error('Failed to load invention SCI', e))
                                        );
                                    }
                                    await Promise.all(invPricePromises);
                                }
                            }
                        })
                        .catch(e => console.error('Failed to load invention source', e))
                );
            }

            // EIV (cached per blueprint type_id)
            if (!(bp.type_id in this.bpEIVs)) {
                promises.push(
                    this.fetchAPI(`/market/eiv/${bp.type_id}`)
                        .then(data => { this.bpEIVs[bp.type_id] = data.eiv; })
                        .catch(e => console.error('Failed to load EIV', e))
                );
            }

            // System cost index (fetched once per system)
            const isReaction = bp.activity_type === 'reaction';
            if (!isReaction && this.systemCostIndex === null) {
                promises.push(
                    this.fetchAPI(`/market/system-cost-index?system=${encodeURIComponent(this.systemName)}`)
                        .then(data => { this.systemCostIndex = data.cost_index; })
                        .catch(e => console.error('Failed to load cost index', e))
                );
            }
            if (isReaction && this.reactionSystemCostIndex === null) {
                promises.push(
                    this.fetchAPI(`/market/system-cost-index?system=${encodeURIComponent(this.reactionSystemName)}&activity=reaction`)
                        .then(data => { this.reactionSystemCostIndex = data.cost_index; })
                        .catch(e => console.error('Failed to load reaction cost index', e))
                );
            }

            // Rig category for this blueprint (when facility is selected)
            if (this.selectedFacility && !(bp.type_id in this.blueprintRigCategories)) {
                promises.push(
                    this.fetchAPI(`/sde/rig-category/${bp.type_id}`)
                        .then(data => { this.blueprintRigCategories[bp.type_id] = data.rig_category; })
                        .catch(e => console.error('Failed to load rig category', e))
                );
            }

            if (promises.length > 0) {
                this.loadingPrices = true;
                await Promise.all(promises);
                this.loadingPrices = false;
            }
        },

        isBpExpanded(bp) {
            const key = this.showDistinct ? (bp._distinctKey || bp.type_id) : bp.item_id;
            return this.expandedBp === key;
        },

        matSellPrice(mat) {
            const p = this.materialPrices[mat.type_id];
            return p && p.sell != null ? p.sell : null;
        },

        matTotalCost(bp, mat) {
            const price = this.matSellPrice(mat);
            if (price == null) return null;
            const qty = this.adjustedMatQuantity(bp, mat);
            return price * qty;
        },

        bpTotalCost(bp) {
            if (!bp.materials) return null;
            let total = 0;
            for (const mat of bp.materials) {
                const cost = this.matTotalCost(bp, mat);
                if (cost == null) return null;
                total += cost;
            }
            return total;
        },

        bpEIV(bp) {
            return this.bpEIVs[bp.type_id] ?? null;
        },

        bpJobCost(bp) {
            const eiv = this.bpEIV(bp);
            const isReaction = bp.activity_type === 'reaction';
            const sci = isReaction ? this.reactionSystemCostIndex : this.systemCostIndex;
            if (eiv == null || sci == null) return null;
            if (this.selectedFacility) {
                // Full formula: EIV * (SCI * (1 + structure_cost_bonus%) + SCC_tax + facility_tax)
                const structCostBonus = this.getStructureCostBonus();
                const facilityTax = this.selectedFacility.facility_tax || 0;
                const sccTax = 0.04; // 4% SCC surcharge
                return eiv * (sci * (1 - structCostBonus) + sccTax + facilityTax);
            }
            return eiv * sci;
        },

        // Product price helpers (products share the materialPrices cache)
        productSellPrice(bp) {
            if (!bp.products || bp.products.length === 0) return null;
            const p = this.materialPrices[bp.products[0].type_id];
            return p && p.sell != null ? p.sell : null;
        },

        productBuyPrice(bp) {
            if (!bp.products || bp.products.length === 0) return null;
            const p = this.materialPrices[bp.products[0].type_id];
            return p && p.buy != null ? p.buy : null;
        },

        productQuantity(bp) {
            if (!bp.products || bp.products.length === 0) return 1;
            return bp.products[0].quantity || 1;
        },

        // Material cost using buy order prices (for "place buy orders" scenario)
        matBuyPrice(mat) {
            const p = this.materialPrices[mat.type_id];
            return p && p.buy != null ? p.buy : null;
        },

        bpTotalCostBuyOrder(bp) {
            if (!bp.materials) return null;
            let total = 0;
            for (const mat of bp.materials) {
                const price = this.matBuyPrice(mat);
                if (price == null) return null;
                const qty = this.adjustedMatQuantity(bp, mat);
                total += price * qty;
            }
            return total;
        },

        // T2 invention cost amortized per manufacturing run
        t2InventionCostPerRun(bp) {
            if (!bp.is_t2) return 0;
            const t1BpId = this.inventionSources[bp.type_id];
            if (!t1BpId) return null;

            const invData = this.inventionData[t1BpId];
            if (!invData) return null;

            // Compute expected cost per success using the T1 bp's invention data
            // We need a temporary bp-like object for the T1 bp
            const fakeBp = { type_id: t1BpId };
            const attemptCost = this.inventionAttemptCost(fakeBp);
            const prob = this.inventionProbability(fakeBp);
            const successProb = this.characterSkillsLoaded ? prob.character : prob.maxSkill;
            if (attemptCost == null || successProb <= 0) return null;

            const costPerSuccess = attemptCost / successProb;

            // Get output runs for this T2 product
            const output = this.inventionOutput(fakeBp);
            const runs = output.runs || 1;

            return costPerSuccess / runs;
        },

        // Full profit calculation
        // inputMode: 'sell' (instant buy at sell price) or 'buy' (place buy orders at buy price)
        // outputMode: 'sell' (instant sell at buy price) or 'order' (sell order at sell price)
        bpProfit(bp, inputMode, outputMode) {
            const qty = this.productQuantity(bp);

            // Revenue
            let unitPrice;
            if (outputMode === 'sell') {
                unitPrice = this.productBuyPrice(bp);  // instant sell fills buy orders
            } else {
                unitPrice = this.productSellPrice(bp);  // sell order at sell price
            }
            if (unitPrice == null) return null;
            const grossRevenue = unitPrice * qty;

            // Sales tax always applies when selling
            const salesTax = grossRevenue * this.salesTaxRate;

            // Broker fee on sell order (only when placing an order)
            const sellBrokerFee = outputMode === 'order' ? grossRevenue * this.brokerFeeRate : 0;

            const revenue = grossRevenue - salesTax - sellBrokerFee;

            // Material cost
            let materialCost;
            if (inputMode === 'sell') {
                materialCost = this.bpTotalCost(bp);  // instant buy at sell price
            } else {
                materialCost = this.bpTotalCostBuyOrder(bp);  // buy orders at buy price
            }
            if (materialCost == null) return null;

            // Broker fee on buy orders for materials
            const buyBrokerFee = inputMode === 'buy' ? materialCost * this.brokerFeeRate : 0;

            // Job cost
            const jobCost = this.bpJobCost(bp) || 0;

            // Invention cost (T2 only)
            const inventionCost = this.t2InventionCostPerRun(bp) || 0;

            const totalCost = materialCost + buyBrokerFee + jobCost + inventionCost;
            const profit = revenue - totalCost;
            const margin = grossRevenue > 0 ? profit / grossRevenue : 0;

            return {
                grossRevenue,
                salesTax,
                sellBrokerFee,
                revenue,
                materialCost,
                buyBrokerFee,
                jobCost,
                inventionCost,
                totalCost,
                profit,
                margin,
            };
        },

        facilityStructureName() {
            if (!this.selectedFacility) return '';
            const s = this.structures[String(this.selectedFacility.structure_type_id)];
            return s ? s.name : 'Unknown';
        },

        facilitySecLabel() {
            if (!this.facilitySystemSecurity) return '';
            const sec = this.facilitySystemSecurity.security;
            if (sec >= 0.45) return 'Highsec';
            if (sec >= 0.05) return 'Lowsec';
            return 'Nullsec';
        },

        formatPercent(value) {
            if (value == null) return '\u2014';
            return (value * 100).toFixed(2) + '%';
        },

        formatISK(value) {
            if (value == null) return '\u2014';
            if (value >= 1e9) return (value / 1e9).toFixed(2) + 'B';
            if (value >= 1e6) return (value / 1e6).toFixed(2) + 'M';
            if (value >= 1e3) return (value / 1e3).toFixed(1) + 'K';
            return value.toFixed(2);
        },

        formatQuantity(n) {
            return n.toLocaleString();
        },

        formatDuration(seconds) {
            if (seconds == null || seconds <= 0) return '\u2014';
            const h = Math.floor(seconds / 3600);
            const m = Math.floor((seconds % 3600) / 60);
            if (h > 0) return `${h}h ${m}m`;
            return `${m}m`;
        },

        // Invention methods
        bpHasInvention(bp) {
            return bp.has_invention === true;
        },

        isInventionMode(bp) {
            return this.inventionMode[bp.type_id] === true;
        },

        async setActivityMode(bp, mode) {
            if (mode === 'invention') {
                this.inventionMode[bp.type_id] = true;
                const promises = [];
                if (!this.inventionData[bp.type_id]) {
                    promises.push(this.loadInventionData(bp));
                }
                if (!this.characterSkillsLoaded) {
                    promises.push(this.loadCharacterSkills());
                }
                await Promise.all(promises);
            } else {
                this.inventionMode[bp.type_id] = false;
            }
        },

        async loadInventionData(bp) {
            const promises = [];

            // Fetch invention data
            promises.push(
                this.fetchAPI(`/sde/blueprints/${bp.type_id}/invention`)
                    .then(data => {
                        this.inventionData[bp.type_id] = data;
                        // Auto-select first product
                        if (data.products && data.products.length > 0 && !this.selectedT2Product[bp.type_id]) {
                            this.selectedT2Product[bp.type_id] = data.products[0].type_id;
                        }
                    })
                    .catch(e => console.error('Failed to load invention data', e))
            );

            // Fetch decryptors (once)
            if (!this.decryptorsLoaded) {
                promises.push(
                    this.fetchAPI('/sde/decryptors')
                        .then(data => {
                            this.decryptors = data;
                            this.decryptorsLoaded = true;
                        })
                        .catch(e => console.error('Failed to load decryptors', e))
                );
            }

            // Fetch invention system cost index (once)
            if (this.inventionSCI === null) {
                promises.push(
                    this.fetchAPI(`/market/system-cost-index?system=${encodeURIComponent(this.systemName)}&activity=invention`)
                        .then(data => { this.inventionSCI = data.cost_index; })
                        .catch(e => console.error('Failed to load invention SCI', e))
                );
            }

            await Promise.all(promises);

            // Now fetch material prices and EIV for the selected product
            const invData = this.inventionData[bp.type_id];
            if (invData) {
                const pricePromises = [];

                // Datacore + material prices
                const matIds = invData.materials
                    .map(m => m.type_id)
                    .filter(id => !(id in this.materialPrices));
                if (matIds.length > 0) {
                    pricePromises.push(
                        this.fetchAPI(`/market/prices?type_ids=${matIds.join(',')}`)
                            .then(data => Object.assign(this.materialPrices, data.prices))
                            .catch(e => console.error('Failed to load invention material prices', e))
                    );
                }

                // Decryptor prices
                if (this.decryptorsLoaded) {
                    const decIds = Object.keys(this.decryptors)
                        .map(Number)
                        .filter(id => !(id in this.materialPrices));
                    if (decIds.length > 0) {
                        pricePromises.push(
                            this.fetchAPI(`/market/prices?type_ids=${decIds.join(',')}`)
                                .then(data => Object.assign(this.materialPrices, data.prices))
                                .catch(e => console.error('Failed to load decryptor prices', e))
                        );
                    }
                }

                // EIV for selected T2 product
                const t2Id = this.selectedT2Product[bp.type_id];
                if (t2Id && !(t2Id in this.inventionEIVs)) {
                    pricePromises.push(
                        this.fetchAPI(`/market/eiv/invention/${t2Id}`)
                            .then(data => { this.inventionEIVs[t2Id] = data.eiv; })
                            .catch(e => console.error('Failed to load invention EIV', e))
                    );
                }

                if (pricePromises.length > 0) {
                    await Promise.all(pricePromises);
                }
            }
        },

        async onT2ProductChange(bp) {
            const t2Id = this.selectedT2Product[bp.type_id];
            if (t2Id && !(t2Id in this.inventionEIVs)) {
                try {
                    const data = await this.fetchAPI(`/market/eiv/invention/${t2Id}`);
                    this.inventionEIVs[t2Id] = data.eiv;
                } catch (e) {
                    console.error('Failed to load invention EIV', e);
                }
            }
        },

        getSelectedProduct(bp) {
            const inv = this.inventionData[bp.type_id];
            if (!inv) return null;
            const t2Id = this.selectedT2Product[bp.type_id];
            return inv.products.find(p => p.type_id === t2Id) || inv.products[0] || null;
        },

        inventionProbability(bp) {
            const product = this.getSelectedProduct(bp);
            if (!product) return { base: 0, character: 0, maxSkill: 0 };
            const baseProb = product.probability || 0;

            const decId = this.selectedDecryptor[bp.type_id];
            const dec = decId ? this.decryptors[String(decId)] : null;
            const decMult = dec ? dec.prob_mult : 1.0;

            // base = probability with no skills
            const base = baseProb * decMult;
            // maxSkill = probability with all skills at 5
            // Formula: base_prob * (1 + encryption/40 + (sci1+sci2)/30) * dec_mult
            const maxSkill = baseProb * (1 + 5 / 40 + (5 + 5) / 30) * decMult;

            // character = probability using actual character skill levels
            let character = maxSkill; // fallback to maxSkill
            const inv = this.inventionData[bp.type_id];
            if (this.characterSkillsLoaded && inv && inv.skills) {
                let encryptionLevel = 0;
                const scienceLevels = [];
                for (const skill of inv.skills) {
                    const level = this.characterSkills[skill.type_id] || 0;
                    if (skill.role === 'encryption') {
                        encryptionLevel = level;
                    } else {
                        scienceLevels.push(level);
                    }
                }
                const sci1 = scienceLevels[0] || 0;
                const sci2 = scienceLevels[1] || 0;
                character = baseProb * (1 + encryptionLevel / 40 + (sci1 + sci2) / 30) * decMult;
            }

            return {
                base,
                character: Math.min(character, 1.0),
                maxSkill: Math.min(maxSkill, 1.0),
            };
        },

        inventionOutput(bp) {
            const product = this.getSelectedProduct(bp);
            if (!product) return { me: 2, te: 4, runs: 1 };

            const decId = this.selectedDecryptor[bp.type_id];
            const dec = decId ? this.decryptors[String(decId)] : null;

            const me = 2 + (dec ? dec.me_mod : 0);
            const te = 4 + (dec ? dec.te_mod : 0);
            const runs = (product.quantity || 1) + (dec ? dec.run_mod : 0);

            return { me: Math.max(0, me), te: Math.max(0, te), runs: Math.max(1, runs) };
        },

        inventionEIV(bp) {
            const t2Id = this.selectedT2Product[bp.type_id];
            if (!t2Id) return null;
            return this.inventionEIVs[t2Id] ?? null;
        },

        inventionJobCost(bp) {
            const eiv = this.inventionEIV(bp);
            const sci = this.inventionSCI;
            if (eiv == null || sci == null) return null;
            if (this.selectedFacility) {
                const structCostBonus = this.getStructureCostBonus();
                const facilityTax = this.selectedFacility.facility_tax || 0;
                const sccTax = 0.04;
                return eiv * (sci * (1 - structCostBonus) + sccTax + facilityTax);
            }
            return eiv * sci;
        },

        inventionAttemptCost(bp) {
            const inv = this.inventionData[bp.type_id];
            if (!inv) return null;

            let total = 0;
            // Datacore costs
            for (const mat of inv.materials) {
                const p = this.materialPrices[mat.type_id];
                if (!p || p.sell == null) return null;
                total += p.sell * mat.quantity;
            }

            // Decryptor cost
            const decId = this.selectedDecryptor[bp.type_id];
            if (decId) {
                const p = this.materialPrices[decId];
                if (!p || p.sell == null) return null;
                total += p.sell;
            }

            // Job cost
            const jobCost = this.inventionJobCost(bp);
            if (jobCost != null) {
                total += jobCost;
            }

            return total;
        },

        characterSkillLevel(skillTypeId) {
            return this.characterSkills[skillTypeId] || 0;
        },

        inventionExpectedCostPerSuccess(bp) {
            const attemptCost = this.inventionAttemptCost(bp);
            const { character, maxSkill } = this.inventionProbability(bp);
            const prob = this.characterSkillsLoaded ? character : maxSkill;
            if (attemptCost == null || prob <= 0) return null;
            return attemptCost / prob;
        },

        // Bulk loading for profit sorting
        collectUncachedTypeIds() {
            const needed = new Set();
            for (const bp of this.filteredBlueprints) {
                if (bp.materials) {
                    for (const m of bp.materials) {
                        if (!(m.type_id in this.materialPrices)) needed.add(m.type_id);
                    }
                }
                if (bp.products) {
                    for (const p of bp.products) {
                        if (!(p.type_id in this.materialPrices)) needed.add(p.type_id);
                    }
                }
            }
            return Array.from(needed);
        },

        collectUncachedEIVBpIds() {
            const needed = [];
            for (const bp of this.filteredBlueprints) {
                if (bp.materials && !(bp.type_id in this.bpEIVs)) {
                    needed.push(bp.type_id);
                }
            }
            return needed;
        },

        collectUncachedRigCategoryBpIds() {
            if (!this.selectedFacility) return [];
            const needed = [];
            for (const bp of this.filteredBlueprints) {
                if (bp.materials && !(bp.type_id in this.blueprintRigCategories)) {
                    needed.push(bp.type_id);
                }
            }
            return needed;
        },

        async bulkLoadForSort(mode) {
            if (this.bulkLoading) return;

            this.sortMode = mode;

            if (mode === 'name') return;

            // Collect what's needed
            const uncachedTypeIds = this.collectUncachedTypeIds();
            const uncachedEIVBpIds = this.collectUncachedEIVBpIds();
            const uncachedRigBpIds = this.collectUncachedRigCategoryBpIds();
            const needMfgSCI = this.systemCostIndex === null;
            const needRxnSCI = this.reactionSystemCostIndex === null;

            // If everything is cached, sort is instant via Alpine reactivity
            if (uncachedTypeIds.length === 0 && uncachedEIVBpIds.length === 0 &&
                uncachedRigBpIds.length === 0 && !needMfgSCI && !needRxnSCI) {
                return;
            }

            this.bulkLoading = true;
            this.bulkProgress = 0;
            this.bulkProgressLabel = 'Preparing...';

            const totalWork = uncachedTypeIds.length + uncachedEIVBpIds.length +
                              uncachedRigBpIds.length + (needMfgSCI ? 1 : 0) + (needRxnSCI ? 1 : 0);
            let completedWork = 0;

            const updateProgress = (delta, label) => {
                completedWork += delta;
                this.bulkProgress = Math.min(100, Math.round((completedWork / totalWork) * 100));
                this.bulkProgressLabel = label;
            };

            try {
                // Phase 1: parallel fast requests (EIVs, rig categories, cost indices)
                const phase1 = [];

                if (uncachedEIVBpIds.length > 0) {
                    phase1.push(
                        this.fetchAPI(`/market/eiv/bulk?type_ids=${uncachedEIVBpIds.join(',')}`)
                            .then(data => {
                                for (const [k, v] of Object.entries(data.eivs)) {
                                    this.bpEIVs[parseInt(k)] = v;
                                }
                                updateProgress(uncachedEIVBpIds.length, 'Loaded EIVs');
                            })
                            .catch(e => {
                                console.error('Bulk EIV failed', e);
                                updateProgress(uncachedEIVBpIds.length, 'EIV error');
                            })
                    );
                }

                if (uncachedRigBpIds.length > 0) {
                    phase1.push(
                        this.fetchAPI(`/sde/rig-categories?type_ids=${uncachedRigBpIds.join(',')}`)
                            .then(data => {
                                for (const [k, v] of Object.entries(data.categories)) {
                                    this.blueprintRigCategories[parseInt(k)] = v;
                                }
                                updateProgress(uncachedRigBpIds.length, 'Loaded rig categories');
                            })
                            .catch(e => {
                                console.error('Bulk rig categories failed', e);
                                updateProgress(uncachedRigBpIds.length, 'Rig category error');
                            })
                    );
                }

                if (needMfgSCI) {
                    phase1.push(
                        this.fetchAPI(`/market/system-cost-index?system=${encodeURIComponent(this.systemName)}`)
                            .then(data => {
                                this.systemCostIndex = data.cost_index;
                                updateProgress(1, 'Loaded manufacturing SCI');
                            })
                            .catch(e => {
                                console.error('Manufacturing SCI failed', e);
                                updateProgress(1, 'SCI error');
                            })
                    );
                }

                if (needRxnSCI) {
                    phase1.push(
                        this.fetchAPI(`/market/system-cost-index?system=${encodeURIComponent(this.reactionSystemName)}&activity=reaction`)
                            .then(data => {
                                this.reactionSystemCostIndex = data.cost_index;
                                updateProgress(1, 'Loaded reaction SCI');
                            })
                            .catch(e => {
                                console.error('Reaction SCI failed', e);
                                updateProgress(1, 'SCI error');
                            })
                    );
                }

                await Promise.all(phase1);

                // Phase 2: market prices in chunks of 50
                if (uncachedTypeIds.length > 0) {
                    const chunkSize = 50;
                    let loaded = 0;
                    for (let i = 0; i < uncachedTypeIds.length; i += chunkSize) {
                        const chunk = uncachedTypeIds.slice(i, i + chunkSize);
                        try {
                            const data = await this.fetchAPI(`/market/prices?type_ids=${chunk.join(',')}`);
                            Object.assign(this.materialPrices, data.prices);
                        } catch (e) {
                            console.error(`Price chunk ${i}/${uncachedTypeIds.length} failed`, e);
                        }
                        loaded += chunk.length;
                        updateProgress(chunk.length, `Loading prices... ${loaded}/${uncachedTypeIds.length} types`);
                    }
                }
            } finally {
                this.bulkLoading = false;
                this.bulkProgress = 100;
                this.bulkProgressLabel = '';
            }
        },
    };
}
