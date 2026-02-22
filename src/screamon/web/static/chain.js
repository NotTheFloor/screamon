// Chain Calculator — Alpine.js Component

const API_BASE = '/api';

let nodeIdCounter = 0;

function chainCalculator() {
    return {
        // Root blueprint info (from URL params)
        typeId: null,
        rootME: 10,
        rootTE: 20,
        runs: 1,
        activityType: 'manufacturing',
        productName: '',

        // Chain tree
        rootNode: null,

        // Facility state
        facilities: [],
        mfgFacilityId: null,
        mfgFacility: null,
        mfgSecurity: null,
        rxnFacilityId: null,
        rxnFacility: null,
        rxnSecurity: null,

        // Caches
        prices: {},
        eivCache: {},
        rigCategoryCache: {},
        blueprintDataCache: {},  // product_type_id -> blueprint API response
        _siblingCounts: {},      // type_id -> count of nodes with that type_id
        _summaryCache: null,     // { materialCost, jobCosts, chainCost, profitSell, profitOrder }
        _costCache: {},          // node.id -> computed cost

        // System cost indices
        mfgSCI: null,
        rxnSCI: null,

        // Settings
        salesTaxRate: 0.036,
        brokerFeeRate: 0.03,
        proratePartialRuns: true,

        // Reference data
        structures: {},
        allRigs: {},

        // Saved chains
        savedChains: [],
        currentChainId: null,
        chainName: '',
        showSaveDialog: false,

        // Link propagation
        linkGroups: {},       // type_id -> { source, me, blueprint_type_id, activity_type, base_materials, ... }
        _propagating: false,  // guard flag to prevent circular propagation

        // UI
        loading: true,

        async init() {
            // Watch settings that affect summary calculations
            this.$watch('proratePartialRuns', () => this._recomputeSummary());
            this.$watch('salesTaxRate', () => this._recomputeSummary());
            this.$watch('brokerFeeRate', () => this._recomputeSummary());

            // Parse URL params
            const params = new URLSearchParams(window.location.search);
            const chainId = parseInt(params.get('chain_id')) || null;
            this.typeId = parseInt(params.get('type_id')) || null;
            this.rootME = parseInt(params.get('me')) || 0;
            this.rootTE = parseInt(params.get('te')) || 0;
            this.runs = parseInt(params.get('runs')) || 1;
            this.activityType = params.get('activity_type') || 'manufacturing';

            // Load saved chains list
            await this.loadSavedChains();

            // If chain_id param, load that saved chain instead
            if (chainId) {
                await this.loadChain(chainId);
                this.loading = false;
                return;
            }

            if (!this.typeId) {
                this.loading = false;
                return;
            }

            try {
                await this._initFromParams();
            } catch (e) {
                console.error('Failed to initialize chain calculator', e);
            } finally {
                this.loading = false;
            }
        },

        async _initFromParams() {
            // Load everything in parallel
            const [materialsData, facilitiesData, structuresData, rigsData, settingsData] = await Promise.all([
                this.fetchAPI(`/sde/blueprints/${this.typeId}/materials`),
                this.fetchAPI('/facilities/'),
                this.fetchAPI('/sde/structures'),
                this.fetchAPI('/sde/rigs'),
                this.fetchAPI('/settings/'),
            ]);

            this.facilities = facilitiesData;
            this.structures = structuresData;
            this.allRigs = rigsData;
            this.salesTaxRate = settingsData.sales_tax_rate;
            this.brokerFeeRate = settingsData.broker_fee_rate;

            // Build root node
            this.productName = materialsData.products?.[0]?.type_name || 'Unknown';
            document.title = `${this.productName} Chain - Screamon`;

            const rootProductQty = materialsData.products?.[0]?.quantity || 1;

            this.rootNode = {
                id: 'root',
                type_id: this.typeId,
                type_name: this.productName,
                required_qty: this.runs * rootProductQty,
                source: 'manufacture',
                blueprint_type_id: this.typeId,
                activity_type: this.activityType,
                me: this.activityType === 'reaction' ? 0 : this.rootME,
                base_product_qty: rootProductQty,
                runs: this.runs,
                base_materials: materialsData.materials,
                rig_category: null,
                products: materialsData.products,
                children: [],
            };

            // Load rig category for root
            try {
                const rigCatData = await this.fetchAPI(`/sde/rig-category/${this.typeId}`);
                this.rootNode.rig_category = rigCatData.rig_category;
                this.rigCategoryCache[this.typeId] = rigCatData.rig_category;
            } catch (e) {
                // No rig category available
            }

            // Build children for root
            this.buildChildren(this.rootNode);
            this._rebuildSiblingCounts();

            // Load prices for all type_ids in tree
            await this.loadAllPrices();

            // Load EIV and SCI for job cost calculations
            await this.loadJobCostData();
            this._recomputeSummary();
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

        // Cached blueprint data fetch (all siblings share same type_id → same response)
        async _fetchBlueprintData(typeId) {
            if (typeId in this.blueprintDataCache) {
                return this.blueprintDataCache[typeId];
            }
            const data = await this.fetchAPI(`/sde/blueprint-for-product/${typeId}`);
            this.blueprintDataCache[typeId] = data;
            return data;
        },

        // Build child nodes from a parent's base_materials
        buildChildren(parentNode) {
            parentNode.children = [];
            if (!parentNode.base_materials) return;

            for (const mat of parentNode.base_materials) {
                const adjustedQty = this.adjustedMatQuantity(parentNode, mat);
                const totalQty = adjustedQty * parentNode.runs;

                const child = {
                    id: 'node_' + (++nodeIdCounter),
                    type_id: mat.type_id,
                    type_name: mat.type_name,
                    required_qty: totalQty,
                    source: 'buy',
                    can_manufacture: undefined, // unknown until checked
                    blueprint_type_id: null,
                    activity_type: null,
                    me: 0,
                    base_product_qty: 1,
                    runs: totalQty,
                    base_materials: null,
                    rig_category: null,
                    linked: true,
                    children: [],
                };

                parentNode.children.push(child);
            }
        },

        // Recalculate quantities for all children of a node
        recalcChildren(parentNode) {
            if (!parentNode.base_materials || !parentNode.children) return;

            for (let i = 0; i < parentNode.base_materials.length; i++) {
                const mat = parentNode.base_materials[i];
                const child = parentNode.children[i];
                if (!child) continue;

                const adjustedQty = this.adjustedMatQuantity(parentNode, mat);
                const totalQty = adjustedQty * parentNode.runs;
                child.required_qty = totalQty;

                if (child.source === 'manufacture' && child.base_product_qty > 0) {
                    child.runs = Math.ceil(totalQty / child.base_product_qty);
                    // Recursively update sub-children
                    this.recalcChildren(child);
                } else {
                    child.runs = totalQty;
                }
            }
        },

        // Material quantity adjusted for ME + facility bonuses
        adjustedMatQuantity(node, mat) {
            const me = node.activity_type === 'reaction' ? 0 : (node.me || 0);
            const facility = this.getFacilityForActivity(node.activity_type);
            const strBonus = this.getStructureMatBonus(facility);
            const rigBonus = this.getApplicableRigMatBonus(facility, node);
            const adjusted = mat.quantity * (1 - me / 100) * strBonus * rigBonus;
            return Math.max(1, Math.ceil(adjusted));
        },

        // Get facility for an activity type
        getFacilityForActivity(activityType) {
            if (activityType === 'reaction') {
                return this.rxnFacility;
            }
            return this.mfgFacility;
        },

        getSecurityForActivity(activityType) {
            if (activityType === 'reaction') {
                return this.rxnSecurity;
            }
            return this.mfgSecurity;
        },

        getStructureMatBonus(facility) {
            if (!facility) return 1.0;
            const struct = this.structures[String(facility.structure_type_id)];
            return struct ? struct.mat_bonus : 1.0;
        },

        getStructureCostBonus(facility) {
            if (!facility) return 0;
            const struct = this.structures[String(facility.structure_type_id)];
            if (!struct) return 0;
            return 1 - struct.cost_bonus;
        },

        getApplicableRigMatBonus(facility, node) {
            if (!facility) return 1.0;
            const category = node.rig_category || this.rigCategoryCache[node.blueprint_type_id];
            if (!category) return 1.0;

            const security = this.getSecurityForActivity(node.activity_type);
            const rigSlots = [
                facility.rig1_type_id,
                facility.rig2_type_id,
                facility.rig3_type_id,
            ];

            let bestBonus = 0;
            for (const rigId of rigSlots) {
                if (!rigId) continue;
                const rig = this.allRigs[String(rigId)];
                if (!rig) continue;
                if (rig.rig_category === category || rig.rig_category === 'ship') {
                    if (rig.mat_bonus < bestBonus) {
                        bestBonus = rig.mat_bonus;
                    }
                }
            }

            if (bestBonus === 0) return 1.0;
            const secMult = security ? security.rig_multiplier : 1.0;
            return 1 + (bestBonus / 100) * secMult;
        },

        // Set source mode for a node (with link propagation)
        async setSource(node, source) {
            if (node.source === source) return;
            await this._applySource(node, source);

            // Propagate to linked siblings if not already propagating
            if (node.linked && !this._propagating) {
                await this._propagateConfig(node);
            }
            this._recomputeSummary();
        },

        // Apply source to a single node (no propagation)
        async _applySource(node, source, { skipPriceLoad = false } = {}) {
            if (node.source === source) return;

            if (source === 'manufacture') {
                // Check if we can manufacture this
                if (node.can_manufacture === false) return;

                try {
                    const data = await this._fetchBlueprintData(node.type_id);
                    node.blueprint_type_id = data.blueprint_type_id;
                    node.activity_type = data.activity_type;
                    node.me = data.activity_type === 'reaction' ? 0 : 0; // default ME 0 for sub-jobs
                    node.base_product_qty = data.products?.[0]?.quantity || 1;
                    node.runs = Math.ceil(node.required_qty / node.base_product_qty);
                    node.base_materials = data.materials;
                    node.rig_category = data.rig_category;
                    node.can_manufacture = true;
                    this.rigCategoryCache[data.blueprint_type_id] = data.rig_category;

                    node.source = source;
                    this.buildChildren(node);

                    // Auto-apply link group defaults to newly created children
                    await this.applyLinkGroupDefaults(node, { skipPriceLoad });

                    if (!skipPriceLoad) {
                        // Load prices and EIV for new materials
                        await Promise.all([
                            this.loadAllPrices(),
                            this.loadEIVForNode(node),
                        ]);
                    }
                } catch (e) {
                    if (e.message.includes('404')) {
                        node.can_manufacture = false;
                    } else {
                        console.error('Failed to load blueprint for product', e);
                    }
                    return;
                }
            } else {
                node.source = source;
                node.children = [];
            }

            this._rebuildSiblingCounts();
        },

        // Event handlers
        onRunsChange() {
            if (!this.rootNode) return;
            this.rootNode.runs = this.runs;
            this.rootNode.required_qty = this.runs * this.rootNode.base_product_qty;
            this.recalcChildren(this.rootNode);
            this._recomputeSummary();
        },

        onMEChange(node) {
            if (node.activity_type === 'reaction') {
                node.me = 0;
            }
            this.recalcChildren(node);

            // Propagate ME to linked siblings
            if (node.linked && !this._propagating) {
                this._propagateME(node);
            }
            this._recomputeSummary();
        },

        // Flatten tree for rendering
        get flattenedTree() {
            const result = [];
            if (!this.rootNode) return result;

            const walk = (node, depth) => {
                for (const child of (node.children || [])) {
                    result.push({ node: child, depth });
                    if (child.source === 'manufacture' && child.children) {
                        walk(child, depth + 1);
                    }
                }
            };
            walk(this.rootNode, 0);
            return result;
        },

        get rootProductQty() {
            if (!this.rootNode?.products?.[0]) return 1;
            return this.rootNode.products[0].quantity || 1;
        },

        // Prorate: when a manufactured node produces more than required,
        // only charge the fraction actually consumed (e.g. need 700, run produces 1500 → 0.467).
        // Leftovers are used elsewhere and shouldn't be fully costed to this product.
        nodeProrateFactor(node) {
            if (!this.proratePartialRuns) return 1.0;
            if (node.source !== 'manufacture') return 1.0;
            const totalOutput = node.runs * node.base_product_qty;
            if (totalOutput <= 0 || node.required_qty >= totalOutput) return 1.0;
            return node.required_qty / totalOutput;
        },

        // Cost calculations (cached per render cycle)
        nodeCost(node) {
            if (node.id in this._costCache) return this._costCache[node.id];
            const cost = this._computeNodeCost(node);
            this._costCache[node.id] = cost;
            return cost;
        },

        _computeNodeCost(node) {
            if (node.source === 'buy') {
                const p = this.prices[node.type_id];
                if (!p || p.sell == null) return null;
                return p.sell * node.required_qty;
            }
            if (node.source === 'order') {
                const p = this.prices[node.type_id];
                if (!p || p.buy == null) return null;
                return p.buy * node.required_qty + p.buy * node.required_qty * this.brokerFeeRate;
            }
            if (node.source === 'produce') {
                // Opportunity cost: buy price * (1 - sales tax)
                const p = this.prices[node.type_id];
                if (!p || p.buy == null) return null;
                return p.buy * node.required_qty * (1 - this.salesTaxRate);
            }
            if (node.source === 'manufacture') {
                // Sum of children costs + job cost, prorated if partial run
                let fullCost = 0;
                for (const child of (node.children || [])) {
                    const childCost = this.nodeCost(child);
                    if (childCost == null) return null;
                    fullCost += childCost;
                }
                const jc = this.nodeJobCost(node);
                if (jc != null) fullCost += jc;
                return fullCost * this.nodeProrateFactor(node);
            }
            return null;
        },

        nodeJobCost(node) {
            if (node.source !== 'manufacture' || !node.blueprint_type_id) return null;

            const eiv = this.eivCache[node.blueprint_type_id];
            if (eiv == null) return null;

            const isReaction = node.activity_type === 'reaction';
            const sci = isReaction ? this.rxnSCI : this.mfgSCI;
            if (sci == null) return null;

            const facility = this.getFacilityForActivity(node.activity_type);
            let jobCostPerRun;
            if (facility) {
                const structCostBonus = this.getStructureCostBonus(facility);
                const facilityTax = facility.facility_tax || 0;
                const sccTax = 0.04;
                jobCostPerRun = eiv * (sci * (1 - structCostBonus) + sccTax + facilityTax);
            } else {
                jobCostPerRun = eiv * sci;
            }
            return jobCostPerRun * node.runs;
        },

        // Aggregate costs (cached — read from _summaryCache)
        totalMaterialCost() {
            return this._summaryCache?.materialCost ?? this._computeTotalMaterialCost();
        },

        _computeTotalMaterialCost() {
            return this._sumLeafCosts(this.rootNode, this.nodeProrateFactor(this.rootNode));
        },

        _sumLeafCosts(node, factor) {
            if (!node) return 0;
            let total = 0;
            for (const child of (node.children || [])) {
                if (child.source === 'manufacture') {
                    const childFactor = factor * this.nodeProrateFactor(child);
                    total += this._sumLeafCosts(child, childFactor);
                } else {
                    const cost = this.nodeCost(child);
                    if (cost != null) total += cost * factor;
                }
            }
            return total;
        },

        totalJobCosts() {
            return this._summaryCache?.jobCosts ?? this._computeTotalJobCosts();
        },

        _computeTotalJobCosts() {
            return this._sumJobCosts(this.rootNode, this.nodeProrateFactor(this.rootNode));
        },

        _sumJobCosts(node, factor) {
            if (!node) return 0;
            let total = 0;
            // Include this node's job cost if it's a manufacture node
            if (node.source === 'manufacture' || node === this.rootNode) {
                const jc = this.nodeJobCost(node);
                if (jc != null) total += jc * factor;
            }
            for (const child of (node.children || [])) {
                if (child.source === 'manufacture') {
                    const childFactor = factor * this.nodeProrateFactor(child);
                    total += this._sumJobCosts(child, childFactor);
                }
            }
            return total;
        },

        totalChainCost() {
            return this._summaryCache?.chainCost ?? this._computeTotalChainCost();
        },

        _computeTotalChainCost() {
            const cost = this.nodeCost(this.rootNode);
            return cost != null ? cost : 0;
        },

        // Product price helpers
        productSellPrice() {
            if (!this.rootNode?.products?.[0]) return null;
            const p = this.prices[this.rootNode.products[0].type_id];
            return p?.sell ?? null;
        },

        productBuyPrice() {
            if (!this.rootNode?.products?.[0]) return null;
            const p = this.prices[this.rootNode.products[0].type_id];
            return p?.buy ?? null;
        },

        chainProfit(outputMode) {
            if (outputMode === 'sell') {
                return this._summaryCache?.profitSell ?? this._computeChainProfit('sell');
            }
            return this._summaryCache?.profitOrder ?? this._computeChainProfit('order');
        },

        _computeChainProfit(outputMode) {
            const productTypeId = this.rootNode?.products?.[0]?.type_id;
            if (!productTypeId) return null;

            const totalProductQty = this.runs * this.rootProductQty;
            let unitPrice;
            if (outputMode === 'sell') {
                unitPrice = this.productBuyPrice(); // instant sell fills buy orders
            } else {
                unitPrice = this.productSellPrice(); // sell order at sell price
            }
            if (unitPrice == null) return null;

            const grossRevenue = unitPrice * totalProductQty;
            const salesTax = grossRevenue * this.salesTaxRate;
            const brokerFee = outputMode === 'order' ? grossRevenue * this.brokerFeeRate : 0;
            const revenue = grossRevenue - salesTax - brokerFee;

            const chainCost = this.totalChainCost();
            const profit = revenue - chainCost;
            const margin = grossRevenue > 0 ? profit / grossRevenue : 0;

            return { grossRevenue, salesTax, brokerFee, revenue, profit, margin };
        },

        // Price loading
        collectAllTypeIds(node) {
            const ids = new Set();
            if (!node) return ids;
            ids.add(node.type_id);
            // Add product type_ids
            for (const p of (node.products || [])) {
                ids.add(p.type_id);
            }
            for (const child of (node.children || [])) {
                for (const id of this.collectAllTypeIds(child)) {
                    ids.add(id);
                }
            }
            return ids;
        },

        async loadAllPrices() {
            const allIds = this.collectAllTypeIds(this.rootNode);
            const needed = [...allIds].filter(id => !(id in this.prices));
            if (needed.length === 0) return;

            const chunkSize = 50;
            for (let i = 0; i < needed.length; i += chunkSize) {
                const chunk = needed.slice(i, i + chunkSize);
                try {
                    const data = await this.fetchAPI(`/market/prices?type_ids=${chunk.join(',')}`);
                    for (const [k, v] of Object.entries(data.prices)) {
                        this.prices[parseInt(k)] = v;
                    }
                } catch (e) {
                    console.error('Failed to load prices chunk', e);
                }
            }
        },

        async loadJobCostData() {
            const promises = [];

            // Load EIV for root node
            if (this.rootNode?.blueprint_type_id && !(this.rootNode.blueprint_type_id in this.eivCache)) {
                promises.push(
                    this.fetchAPI(`/market/eiv/${this.rootNode.blueprint_type_id}`)
                        .then(data => { this.eivCache[this.rootNode.blueprint_type_id] = data.eiv; })
                        .catch(e => console.error('Failed to load root EIV', e))
                );
            }

            // Load manufacturing SCI
            if (this.mfgSCI === null) {
                const system = this.mfgFacility?.system_name || 'Serren';
                promises.push(
                    this.fetchAPI(`/market/system-cost-index?system=${encodeURIComponent(system)}`)
                        .then(data => { this.mfgSCI = data.cost_index; })
                        .catch(e => console.error('Failed to load manufacturing SCI', e))
                );
            }

            // Load reaction SCI
            if (this.rxnSCI === null) {
                const system = this.rxnFacility?.system_name || 'Obalyu';
                promises.push(
                    this.fetchAPI(`/market/system-cost-index?system=${encodeURIComponent(system)}&activity=reaction`)
                        .then(data => { this.rxnSCI = data.cost_index; })
                        .catch(e => console.error('Failed to load reaction SCI', e))
                );
            }

            await Promise.all(promises);
        },

        async loadEIVForNode(node) {
            if (!node.blueprint_type_id || node.blueprint_type_id in this.eivCache) return;
            try {
                const data = await this.fetchAPI(`/market/eiv/${node.blueprint_type_id}`);
                this.eivCache[node.blueprint_type_id] = data.eiv;
            } catch (e) {
                console.error('Failed to load EIV for node', e);
            }
        },

        // Batch load all prices and EIVs for the entire tree (used after bulk operations)
        async _loadAllPricesAndEIV() {
            await this.loadAllPrices();

            // Collect uncached blueprint_type_ids from the tree
            const uncached = [];
            const walk = (node) => {
                if (node.blueprint_type_id && !(node.blueprint_type_id in this.eivCache)) {
                    uncached.push(node.blueprint_type_id);
                }
                for (const child of (node.children || [])) {
                    walk(child);
                }
            };
            if (this.rootNode) walk(this.rootNode);

            const uniqueIds = [...new Set(uncached)];
            if (uniqueIds.length > 0) {
                try {
                    const data = await this.fetchAPI(`/market/eiv/bulk?type_ids=${uniqueIds.join(',')}`);
                    for (const [k, v] of Object.entries(data.eivs || data)) {
                        this.eivCache[parseInt(k)] = v;
                    }
                } catch (e) {
                    console.error('Failed to bulk load EIVs', e);
                }
            }
        },

        // Rebuild sibling count cache (single tree walk)
        _rebuildSiblingCounts() {
            const counts = {};
            const walk = (node) => {
                for (const child of (node.children || [])) {
                    counts[child.type_id] = (counts[child.type_id] || 0) + 1;
                    if (child.children) walk(child);
                }
            };
            if (this.rootNode) walk(this.rootNode);
            this._siblingCounts = counts;
        },

        // Recompute all summary values (clears cost cache, then computes once)
        _recomputeSummary() {
            this._costCache = {};
            if (!this.rootNode) {
                this._summaryCache = null;
                return;
            }
            this._summaryCache = {
                materialCost: this._computeTotalMaterialCost(),
                jobCosts: this._computeTotalJobCosts(),
                chainCost: this._computeTotalChainCost(),
                profitSell: this._computeChainProfit('sell'),
                profitOrder: this._computeChainProfit('order'),
            };
        },

        // Facility selection
        async selectMfgFacility(id) {
            if (id === '' || id === null) {
                this.mfgFacilityId = null;
                this.mfgFacility = null;
                this.mfgSecurity = null;
            } else {
                this.mfgFacilityId = parseInt(id);
                this.mfgFacility = this.facilities.find(f => f.id === this.mfgFacilityId) || null;
                if (this.mfgFacility) {
                    try {
                        this.mfgSecurity = await this.fetchAPI(
                            `/sde/system-security/${encodeURIComponent(this.mfgFacility.system_name)}`
                        );
                    } catch (e) {
                        this.mfgSecurity = null;
                    }
                    // Reload SCI for new system
                    try {
                        const data = await this.fetchAPI(
                            `/market/system-cost-index?system=${encodeURIComponent(this.mfgFacility.system_name)}`
                        );
                        this.mfgSCI = data.cost_index;
                    } catch (e) {
                        console.error('Failed to load manufacturing SCI', e);
                    }
                }
            }
            // Recalculate quantities based on new facility bonuses
            if (this.rootNode) {
                this.recalcChildren(this.rootNode);
                this._recomputeSummary();
            }
        },

        async selectRxnFacility(id) {
            if (id === '' || id === null) {
                this.rxnFacilityId = null;
                this.rxnFacility = null;
                this.rxnSecurity = null;
            } else {
                this.rxnFacilityId = parseInt(id);
                this.rxnFacility = this.facilities.find(f => f.id === this.rxnFacilityId) || null;
                if (this.rxnFacility) {
                    try {
                        this.rxnSecurity = await this.fetchAPI(
                            `/sde/system-security/${encodeURIComponent(this.rxnFacility.system_name)}`
                        );
                    } catch (e) {
                        this.rxnSecurity = null;
                    }
                    // Reload SCI for new system
                    try {
                        const data = await this.fetchAPI(
                            `/market/system-cost-index?system=${encodeURIComponent(this.rxnFacility.system_name)}&activity=reaction`
                        );
                        this.rxnSCI = data.cost_index;
                    } catch (e) {
                        console.error('Failed to load reaction SCI', e);
                    }
                }
            }
            // Recalculate quantities based on new facility bonuses
            if (this.rootNode) {
                this.recalcChildren(this.rootNode);
                this._recomputeSummary();
            }
        },

        // Facility display helpers
        structureName(facility) {
            if (!facility) return '';
            const s = this.structures[String(facility.structure_type_id)];
            return s ? s.name : 'Unknown';
        },

        secLabel(security) {
            if (!security) return '';
            const sec = security.security;
            if (sec >= 0.45) return 'Highsec';
            if (sec >= 0.05) return 'Lowsec';
            return 'Nullsec';
        },

        // Saved chain methods
        async loadSavedChains() {
            try {
                this.savedChains = await this.fetchAPI('/chains/');
            } catch (e) {
                console.error('Failed to load saved chains', e);
            }
        },

        serializeTree(node) {
            if (!node || !node.children) return [];
            const result = [];
            for (const child of node.children) {
                const entry = { type_id: child.type_id, source: child.source };
                if (child.source === 'manufacture') {
                    entry.me = child.me || 0;
                    if (child.children && child.children.length > 0) {
                        entry.children = this.serializeTree(child);
                    }
                }
                // Only serialize linked=false (default true omitted for compact JSON)
                if (child.linked === false) {
                    entry.linked = false;
                }
                result.push(entry);
            }
            return result;
        },

        async saveChain() {
            if (!this.chainName.trim() || !this.rootNode) return;

            const payload = {
                name: this.chainName.trim(),
                type_id: this.typeId,
                root_me: this.rootME,
                root_te: this.rootTE,
                runs: this.runs,
                activity_type: this.activityType,
                node_tree: this.serializeTree(this.rootNode),
                mfg_facility_id: this.mfgFacilityId,
                rxn_facility_id: this.rxnFacilityId,
                prorate_partial_runs: this.proratePartialRuns,
            };

            try {
                if (this.currentChainId) {
                    await this.fetchAPI(`/chains/${this.currentChainId}`, {
                        method: 'PUT',
                        body: JSON.stringify(payload),
                    });
                } else {
                    const result = await this.fetchAPI('/chains/', {
                        method: 'POST',
                        body: JSON.stringify(payload),
                    });
                    this.currentChainId = result.id;
                }
                this.showSaveDialog = false;
                await this.loadSavedChains();
            } catch (e) {
                console.error('Failed to save chain', e);
            }
        },

        async saveChainAs() {
            this.currentChainId = null;
            this.showSaveDialog = true;
        },

        async loadChain(id) {
            this.loading = true;
            try {
                const chain = await this.fetchAPI(`/chains/${id}`);

                // Set state from saved chain
                this.typeId = chain.type_id;
                this.rootME = chain.root_me;
                this.rootTE = chain.root_te;
                this.runs = chain.runs;
                this.activityType = chain.activity_type;
                this.proratePartialRuns = chain.prorate_partial_runs;
                this.currentChainId = chain.id;
                this.chainName = chain.name;

                // Initialize tree from SDE data
                const [materialsData, facilitiesData, structuresData, rigsData, settingsData] = await Promise.all([
                    this.fetchAPI(`/sde/blueprints/${this.typeId}/materials`),
                    this.fetchAPI('/facilities/'),
                    this.fetchAPI('/sde/structures'),
                    this.fetchAPI('/sde/rigs'),
                    this.fetchAPI('/settings/'),
                ]);

                this.facilities = facilitiesData;
                this.structures = structuresData;
                this.allRigs = rigsData;
                this.salesTaxRate = settingsData.sales_tax_rate;
                this.brokerFeeRate = settingsData.broker_fee_rate;

                // Build root node
                this.productName = materialsData.products?.[0]?.type_name || 'Unknown';
                document.title = `${this.chainName} - ${this.productName} Chain - Screamon`;

                const rootProductQty = materialsData.products?.[0]?.quantity || 1;
                this.rootNode = {
                    id: 'root',
                    type_id: this.typeId,
                    type_name: this.productName,
                    required_qty: this.runs * rootProductQty,
                    source: 'manufacture',
                    blueprint_type_id: this.typeId,
                    activity_type: this.activityType,
                    me: this.activityType === 'reaction' ? 0 : this.rootME,
                    base_product_qty: rootProductQty,
                    runs: this.runs,
                    base_materials: materialsData.materials,
                    rig_category: null,
                    products: materialsData.products,
                    children: [],
                };

                // Load rig category for root
                try {
                    const rigCatData = await this.fetchAPI(`/sde/rig-category/${this.typeId}`);
                    this.rootNode.rig_category = rigCatData.rig_category;
                    this.rigCategoryCache[this.typeId] = rigCatData.rig_category;
                } catch (e) {}

                // Restore facility selections
                if (chain.mfg_facility_id) {
                    await this.selectMfgFacility(chain.mfg_facility_id);
                }
                if (chain.rxn_facility_id) {
                    await this.selectRxnFacility(chain.rxn_facility_id);
                }

                // Build children, then apply saved tree config (skip per-node price loads)
                this.buildChildren(this.rootNode);
                await this.applyTreeConfig(this.rootNode, chain.node_tree || [], { skipPriceLoad: true });

                // Rebuild link groups from restored tree state
                this._rebuildLinkGroups();
                this._rebuildSiblingCounts();

                // Load prices and job cost data in one batch
                await this._loadAllPricesAndEIV();
                await this.loadJobCostData();
                this._recomputeSummary();

                // Update URL without reloading
                const url = new URL(window.location);
                url.searchParams.set('chain_id', id);
                url.searchParams.delete('type_id');
                url.searchParams.delete('me');
                url.searchParams.delete('te');
                url.searchParams.delete('runs');
                url.searchParams.delete('activity_type');
                window.history.replaceState({}, '', url);

            } catch (e) {
                console.error('Failed to load chain', e);
            } finally {
                this.loading = false;
            }
        },

        async applyTreeConfig(parentNode, savedChildren, { skipPriceLoad = false } = {}) {
            if (!savedChildren || !parentNode.children) return;

            for (const saved of savedChildren) {
                // Find matching child by type_id
                const child = parentNode.children.find(c => c.type_id === saved.type_id);
                if (!child) continue;

                // Restore linked state (default true when not present)
                if (saved.linked === false) {
                    child.linked = false;
                }

                if (saved.source === 'manufacture') {
                    // Use _applySource to avoid propagation during tree restore
                    await this._applySource(child, 'manufacture', { skipPriceLoad });
                    if (saved.me != null) {
                        child.me = saved.me;
                        this.recalcChildren(child);
                    }
                    if (saved.children && saved.children.length > 0) {
                        await this.applyTreeConfig(child, saved.children, { skipPriceLoad });
                    }
                } else if (saved.source !== 'buy') {
                    await this._applySource(child, saved.source, { skipPriceLoad });
                }
            }
        },

        async deleteChain(id) {
            if (!confirm('Delete this saved chain?')) return;
            try {
                await this.fetchAPI(`/chains/${id}`, { method: 'DELETE' });
                if (this.currentChainId === id) {
                    this.currentChainId = null;
                    this.chainName = '';
                }
                await this.loadSavedChains();
            } catch (e) {
                console.error('Failed to delete chain', e);
            }
        },

        // Link propagation methods

        // Find all child nodes (not root) with a given type_id
        findNodesByTypeId(typeId) {
            const results = [];
            const walk = (node) => {
                for (const child of (node.children || [])) {
                    if (child.type_id === typeId) {
                        results.push(child);
                    }
                    if (child.children) {
                        walk(child);
                    }
                }
            };
            if (this.rootNode) walk(this.rootNode);
            return results;
        },

        // Count other nodes with same type_id (for UI badge) — uses cached counts
        countLinkedSiblings(node) {
            return (this._siblingCounts[node.type_id] || 0) - 1;
        },

        // Propagate source + ME + sub-tree config from sourceNode to all linked siblings
        async _propagateConfig(sourceNode) {
            this._propagating = true;
            try {
                // Update link group canonical config
                const config = {
                    source: sourceNode.source,
                    me: sourceNode.me,
                };
                if (sourceNode.source === 'manufacture') {
                    config.blueprint_type_id = sourceNode.blueprint_type_id;
                    config.activity_type = sourceNode.activity_type;
                    config.subTree = this.serializeTree(sourceNode);
                }
                this.linkGroups[sourceNode.type_id] = config;

                // Find all other linked nodes with same type_id
                const siblings = this.findNodesByTypeId(sourceNode.type_id)
                    .filter(n => n !== sourceNode && n.linked);

                for (const sibling of siblings) {
                    if (sourceNode.source === 'manufacture') {
                        await this._applySource(sibling, 'manufacture', { skipPriceLoad: true });
                        if (config.me != null) {
                            sibling.me = config.me;
                            this.recalcChildren(sibling);
                        }
                        // Apply sub-tree config if present
                        if (config.subTree && config.subTree.length > 0) {
                            await this.applyTreeConfig(sibling, config.subTree, { skipPriceLoad: true });
                        }
                    } else {
                        await this._applySource(sibling, sourceNode.source, { skipPriceLoad: true });
                    }
                }

                // Single batch load for all new prices + EIVs
                await this._loadAllPricesAndEIV();
            } finally {
                this._propagating = false;
            }
            this._rebuildSiblingCounts();
            this._recomputeSummary();
        },

        // Propagate ME-only changes to linked siblings
        _propagateME(sourceNode) {
            this._propagating = true;
            try {
                // Update link group ME
                if (this.linkGroups[sourceNode.type_id]) {
                    this.linkGroups[sourceNode.type_id].me = sourceNode.me;
                }

                const siblings = this.findNodesByTypeId(sourceNode.type_id)
                    .filter(n => n !== sourceNode && n.linked && n.source === 'manufacture');

                for (const sibling of siblings) {
                    sibling.me = sourceNode.me;
                    this.recalcChildren(sibling);
                }
            } finally {
                this._propagating = false;
            }
        },

        // After buildChildren, check new children against linkGroups and auto-apply
        async applyLinkGroupDefaults(parentNode, { skipPriceLoad = false } = {}) {
            if (!parentNode.children) return;
            for (const child of parentNode.children) {
                if (!child.linked) continue;
                const group = this.linkGroups[child.type_id];
                if (!group || group.source === 'buy') continue;

                // Apply the stored config
                if (group.source === 'manufacture') {
                    await this._applySource(child, 'manufacture', { skipPriceLoad });
                    if (group.me != null) {
                        child.me = group.me;
                        this.recalcChildren(child);
                    }
                    if (group.subTree && group.subTree.length > 0) {
                        await this.applyTreeConfig(child, group.subTree, { skipPriceLoad });
                    }
                } else {
                    await this._applySource(child, group.source, { skipPriceLoad });
                }
            }
        },

        // Toggle linked state on a node
        async toggleLink(node) {
            node.linked = !node.linked;
            // On re-link, adopt canonical config from linkGroups
            if (node.linked) {
                const group = this.linkGroups[node.type_id];
                if (group && group.source !== node.source) {
                    this._propagating = true;
                    try {
                        if (group.source === 'manufacture') {
                            await this._applySource(node, 'manufacture', { skipPriceLoad: true });
                            if (group.me != null) {
                                node.me = group.me;
                                this.recalcChildren(node);
                            }
                            if (group.subTree && group.subTree.length > 0) {
                                await this.applyTreeConfig(node, group.subTree, { skipPriceLoad: true });
                            }
                        } else {
                            await this._applySource(node, group.source, { skipPriceLoad: true });
                        }
                        await this._loadAllPricesAndEIV();
                    } finally {
                        this._propagating = false;
                    }
                } else if (group && group.source === 'manufacture' && group.me != null && node.me !== group.me) {
                    node.me = group.me;
                    this.recalcChildren(node);
                }
            }
            this._rebuildSiblingCounts();
            this._recomputeSummary();
        },

        // Rebuild linkGroups from current tree state (called after loading a saved chain)
        _rebuildLinkGroups() {
            this.linkGroups = {};
            const walk = (node) => {
                for (const child of (node.children || [])) {
                    if (child.linked && child.source !== 'buy' && !(child.type_id in this.linkGroups)) {
                        const config = {
                            source: child.source,
                            me: child.me,
                        };
                        if (child.source === 'manufacture') {
                            config.blueprint_type_id = child.blueprint_type_id;
                            config.activity_type = child.activity_type;
                            config.subTree = this.serializeTree(child);
                        }
                        this.linkGroups[child.type_id] = config;
                    }
                    if (child.children) {
                        walk(child);
                    }
                }
            };
            if (this.rootNode) walk(this.rootNode);
        },

        // Formatting
        formatISK(value) {
            if (value == null) return '\u2014';
            const abs = Math.abs(value);
            const sign = value < 0 ? '-' : '';
            if (abs >= 1e9) return sign + (abs / 1e9).toFixed(2) + 'B';
            if (abs >= 1e6) return sign + (abs / 1e6).toFixed(2) + 'M';
            if (abs >= 1e3) return sign + (abs / 1e3).toFixed(1) + 'K';
            return value.toFixed(2);
        },

        formatPercent(value) {
            if (value == null) return '\u2014';
            return (value * 100).toFixed(2) + '%';
        },

        formatQuantity(n) {
            if (n == null) return '\u2014';
            return n.toLocaleString();
        },
    };
}
