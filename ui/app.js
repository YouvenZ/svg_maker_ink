document.addEventListener('DOMContentLoaded', () => {
    const tabs = document.querySelectorAll('.tab');
    const tabContents = document.querySelectorAll('.tab-content');
    const form = document.getElementById('generator-form');
    const statusMsg = document.getElementById('status-msg');
    const providerSelect = document.getElementById('provider');
    const endpointGroup = document.getElementById('endpoint-group');
    const manualModelGroup = document.getElementById('manual-model-group');
    const syncBtn = document.getElementById('sync-btn');

    // UI Summary Element (add to domestic)
    const summaryDiv = document.createElement('div');
    summaryDiv.style = "font-size: 11px; color: var(--text-secondary); margin-bottom: 10px; text-transform: uppercase;";
    document.getElementById('tab-generator').prepend(summaryDiv);

    const updateSummary = () => {
        const p = providerSelect.value;
        const m = document.getElementById('model').value;
        summaryDiv.innerText = `Active: ${p} | Model: ${mm || m}`;
    };

    const profileGroup = document.getElementById('profile-group');
    const profileSelect = document.getElementById('profile_select');
    const addProfileBtn = document.getElementById('add-profile-btn');

    let availableModels = {}; // Global store for models from backend
    let customProfiles = []; // Global store for profiles
    let providerSettings = {}; // Global store for each provider's settings

    // Initial settings fetch
    const fetchSettings = async () => {
        try {
            const response = await fetch('/get-settings');
            if (response.ok) {
                const settings = await response.json();

                if (settings.available_models) availableModels = settings.available_models;
                if (settings.custom_profiles) customProfiles = settings.custom_profiles;
                if (settings.provider_settings) providerSettings = settings.provider_settings;

                if (settings.prompt) document.getElementById('prompt').value = settings.prompt;

                // Set the model dropdown options based on the provider first
                const updateModelDropdown = (provider) => {
                    const modelSelect = document.getElementById('model');
                    modelSelect.innerHTML = '';
                    if (availableModels[provider]) {
                        availableModels[provider].forEach(m => {
                            const opt = document.createElement('option');
                            opt.value = m;
                            opt.innerText = m;
                            modelSelect.appendChild(opt);
                        });
                    } else {
                        const opt = document.createElement('option');
                        opt.value = 'unknown';
                        opt.innerText = 'Unknown Provider';
                        modelSelect.appendChild(opt);
                    }
                };

                if (settings.provider) {
                    providerSelect.value = settings.provider;
                    updateModelDropdown(settings.provider);

                    // Delay triggering change event so profiles can be populated first
                    setTimeout(() => {
                        providerSelect.dispatchEvent(new Event('change'));

                        // Overwrite with currently active settings (e.g. if a profile was just loaded)
                        const activeP = settings.provider;
                        if (providerSettings[activeP]) {
                            const pData = providerSettings[activeP];
                            if (pData.api_key) document.getElementById('api_key').value = pData.api_key;
                            if (pData.api_endpoint) document.getElementById('api_endpoint').value = pData.api_endpoint;
                            if (pData.manual_model_name) document.getElementById('manual_model_name').value = pData.manual_model_name;
                            if (pData.model) {
                                document.getElementById('model').value = pData.model;
                                // Add to dropdown if 'custom' is not there
                                if (!Array.from(document.getElementById('model').options).some(o => o.value === pData.model)) {
                                    const opt = document.createElement('option');
                                    opt.value = pData.model;
                                    opt.innerText = pData.model;
                                    document.getElementById('model').appendChild(opt);
                                    document.getElementById('model').value = pData.model;
                                }
                            }
                        }
                    }, 50);
                }
                if (settings.manual_model_name) document.getElementById('manual_model_name').value = settings.manual_model_name;
                if (settings.variations) document.getElementById('variations').value = settings.variations;
                if (settings.size) document.getElementById('size').value = settings.size;
                if (settings.aspect_ratio) document.getElementById('aspect_ratio').value = settings.aspect_ratio;
                if (settings.retry_count) document.getElementById('retry_count').value = settings.retry_count;
                if (settings.temperature) {
                    document.getElementById('temperature').value = settings.temperature;
                    document.getElementById('temp-val').innerText = settings.temperature;
                }
                if (settings.position) document.getElementById('position').value = settings.position;
                if (settings.use_selection_context !== undefined) document.getElementById('use_selection_context').checked = settings.use_selection_context;

                updateSummary();
            }
        } catch (err) {
            console.error("Failed to load settings:", err);
            updateSummary();
        }
    };
    fetchSettings();

    let currentHistory = [];

    const fetchHistory = async (filterText = "") => {
        const historyList = document.getElementById('history-list');
        try {
            if (!filterText && currentHistory.length === 0) { // Only fetch from server if no filter and history is empty
                const response = await fetch('/get-history');
                if (response.ok) {
                    currentHistory = await response.json();
                }
            }

            const filtered = currentHistory.filter(entry =>
                entry.prompt.toLowerCase().includes(filterText.toLowerCase()) ||
                entry.model.toLowerCase().includes(filterText.toLowerCase())
            );

            if (filtered.length === 0) {
                historyList.innerHTML = `<p class="empty-msg">${filterText ? 'No matches found.' : 'No history yet. Generate something!'}</p>`;
                return;
            }

            historyList.innerHTML = '';
            filtered.forEach(entry => {
                const item = document.createElement('div');
                item.className = 'history-item';
                const date = new Date(entry.timestamp).toLocaleString();
                item.innerHTML = `
                    <div class="prompt-text">${entry.prompt}</div>
                    <div class="meta-text">
                        <span>${entry.provider} | ${entry.model}</span>
                        <span>${date}</span>
                    </div>
                `;
                item.addEventListener('click', () => {
                    document.getElementById('prompt').value = entry.prompt;
                    if (entry.provider) {
                        providerSelect.value = entry.provider;
                        providerSelect.dispatchEvent(new Event('change'));
                    }
                    // Switch to Generator tab
                    document.querySelector('[data-tab="generator"]').click();
                });
                historyList.appendChild(item);
            });
        } catch (err) {
            console.error("Failed to load history:", err);
            historyList.innerHTML = '<p class="error-msg">Failed to load history.</p>';
        }
    };

    // History Search
    document.getElementById('history-search').addEventListener('input', (e) => {
        fetchHistory(e.target.value);
    });

    // Clear History
    document.getElementById('clear-history-btn').addEventListener('click', async () => {
        if (confirm("Are you sure you want to clear all history?")) {
            try {
                const response = await fetch('/clear-history', { method: 'POST' });
                if (response.ok) {
                    currentHistory = [];
                    fetchHistory();
                }
            } catch (err) {
                console.error("Failed to clear history:", err);
            }
        }
    });

    // Tab Switching
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            const target = tab.getAttribute('data-tab');
            if (target === 'history') fetchHistory();

            // Action area (Generate button) visibility
            const actionArea = document.getElementById('action-area');
            if (target === 'generator') {
                actionArea.classList.remove('hidden');
            } else {
                actionArea.classList.add('hidden');
            }

            tabContents.forEach(content => {
                if (content.id === `tab-${target}`) {
                    content.classList.remove('hidden');
                } else {
                    content.classList.add('hidden');
                }
            });
        });
    });

    // Temperature display update
    const tempSlider = document.getElementById('temperature');
    const tempVal = document.getElementById('temp-val');
    tempSlider.addEventListener('input', () => {
        tempVal.innerText = tempSlider.value;
    });

    // Profile Handling Logic
    const loadProfileData = (profileId) => {
        const pData = providerSettings[profileId] || {};
        document.getElementById('api_key').value = pData.api_key || "";
        document.getElementById('api_endpoint').value = pData.api_endpoint || "";
        document.getElementById('manual_model_name').value = pData.manual_model_name || "";
        if (pData.model) {
            document.getElementById('model').value = pData.model;
        }
        updateSummary();
    };

    const updateProfileDropdown = () => {
        profileSelect.innerHTML = '';
        customProfiles.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.innerText = p.name;
            profileSelect.appendChild(opt);
        });

        // Auto-select provider if it matches a profile ID
        if (customProfiles.some(p => p.id === providerSelect.value)) {
            profileSelect.value = providerSelect.value;
        } else if (customProfiles.length > 0) {
            profileSelect.value = customProfiles[0].id;
            providerSelect.value = customProfiles[0].id; // Sync provider to first profile immediately to avoid desync
        }
    };

    profileSelect.addEventListener('change', () => {
        const selectedId = profileSelect.value;
        // The provider internally is really just the profile ID for custom ones
        const currentProviderOption = Array.from(providerSelect.options).find(o => o.value === selectedId);

        // If the profile ID isn't in the main provider list, we temporarily inject it so backend knows
        if (!currentProviderOption) {
            const opt = document.createElement('option');
            opt.value = selectedId;
            opt.innerText = selectedId;
            opt.hidden = true; // Still grouped visually under "OpenAI Compatible"
            providerSelect.appendChild(opt);
        }

        providerSelect.value = selectedId;
        loadProfileData(selectedId);
    });

    addProfileBtn.addEventListener('click', () => {
        const name = prompt("Enter a name for the new profile:");
        if (name && name.trim() !== '') {
            const id = 'custom_' + Date.now().toString(36);
            customProfiles.push({ id, name });
            providerSettings[id] = {
                api_key: "",
                api_endpoint: "http://localhost:1234/v1",
                manual_model_name: "",
                model: "custom"
            };
            updateProfileDropdown();
            profileSelect.value = id;
            profileSelect.dispatchEvent(new Event('change'));
        }
    });

    // Provider Change UI Logic
    providerSelect.addEventListener('change', () => {
        const val = providerSelect.value;
        let isCustomProfile = customProfiles.some(p => p.id === val);

        if (val === 'ollama' || val === 'openai_compatible' || isCustomProfile) {
            endpointGroup.classList.remove('hidden');
            manualModelGroup.classList.remove('hidden');

            if (val === 'openai_compatible' || isCustomProfile) {
                profileGroup.classList.remove('hidden');
                // Ensure there's at least one default profile if they click OpenAI Compatible
                if (customProfiles.length === 0) {
                    customProfiles.push({ id: 'custom_default', name: 'Default Profile' });
                    updateProfileDropdown();
                    profileSelect.dispatchEvent(new Event('change')); // Force select first
                } else {
                    updateProfileDropdown();
                    // Auto-load data if we switched TO a custom profile
                    if (isCustomProfile) loadProfileData(val);
                }
            } else {
                profileGroup.classList.add('hidden');
                loadProfileData(val);
            }
        } else {
            endpointGroup.classList.add('hidden');
            manualModelGroup.classList.add('hidden');
            profileGroup.classList.add('hidden');
            loadProfileData(val);
        }

        // Keep local static model definitions in sync when provider changes manually
        // For custom profiles, availableModels key might just be 'openai_compatible' logic
        const modelsLookupKey = val.startsWith('custom_') ? 'openai_compatible' : val;

        if (availableModels[modelsLookupKey]) {
            const modelSelect = document.getElementById('model');
            modelSelect.innerHTML = '';
            availableModels[modelsLookupKey].forEach(m => {
                const opt = document.createElement('option');
                opt.value = m;
                opt.innerText = m;
                modelSelect.appendChild(opt);
            });
        }

        updateSummary();
    });

    document.getElementById('manual_model_name').addEventListener('input', updateSummary);
    document.getElementById('model').addEventListener('change', updateSummary);

    // Helper to get all form data
    const getFormData = () => {
        // Save current UI state back to the active provider
        const currentProvider = providerSelect.value;
        providerSettings[currentProvider] = {
            ...providerSettings[currentProvider],
            api_key: document.getElementById('api_key').value,
            api_endpoint: document.getElementById('api_endpoint').value,
            model: document.getElementById('model').value,
            manual_model_name: document.getElementById('manual_model_name').value
        };

        return {
            prompt: document.getElementById('prompt').value,
            prompt_preset: document.getElementById('prompt_preset').value,
            style_hint: document.getElementById('style_hint').value,
            provider: currentProvider,
            provider_settings: providerSettings,
            custom_profiles: customProfiles,
            size: document.getElementById('size').value,
            aspect_ratio: document.getElementById('aspect_ratio').value,
            variations: document.getElementById('variations').value,
            retry_count: document.getElementById('retry_count').value,
            position: document.getElementById('position').value,
            use_selection_context: document.getElementById('use_selection_context').checked
        };
    };

    // Generic save function
    const saveSettings = async (data, btn) => {
        const originalText = btn.innerText;
        btn.innerText = "Saving...";
        btn.disabled = true;

        try {
            const response = await fetch('/save-settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });

            if (response.ok) {
                btn.innerText = "SAVED!";
                btn.style.borderColor = "#4ade80";
                btn.style.color = "#4ade80";
                setTimeout(() => {
                    btn.innerText = originalText;
                    btn.style.borderColor = "";
                    btn.style.color = "";
                    btn.disabled = false;
                }, 2000);
            }
        } catch (err) {
            console.error("Save failed:", err);
            btn.innerText = "ERROR";
            btn.disabled = false;
        }
    };

    // Event listeners for Save buttons
    const saveSetupBtn = document.getElementById('save-setup-btn');
    if (saveSetupBtn) {
        saveSetupBtn.addEventListener('click', (e) => {
            saveSettings(getFormData(), e.target);
        });
    }

    const saveStylesBtn = document.getElementById('save-styles');
    if (saveStylesBtn) {
        saveStylesBtn.addEventListener('click', (e) => {
            saveSettings(getFormData(), e.target);
        });
    }

    // Form Submission (Generator only)
    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const data = getFormData();
        if (!data.prompt || data.prompt.length < 3) {
            statusMsg.innerText = "Please provide a descriptive prompt.";
            statusMsg.style.color = "#ef4444";
            statusMsg.classList.remove('hidden');
            return;
        }

        const submitBtn = document.getElementById('generate-btn');
        const progressContainer = document.getElementById('progress-container');
        const progressFill = document.getElementById('progress-fill');
        const progressStatus = document.getElementById('progress-status');

        if (!submitBtn) return;

        submitBtn.disabled = true;
        submitBtn.innerText = "Processing...";
        if (progressContainer) progressContainer.classList.remove('hidden');
        progressFill.style.width = '10%';
        progressStatus.innerText = "Connecting to server...";

        try {
            const response = await fetch('/submit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });

            if (response.ok) {
                const poll = setInterval(async () => {
                    try {
                        const statusRes = await fetch('/status');
                        const statusData = await statusRes.json();

                        progressFill.style.width = statusData.progress + '%';
                        progressStatus.innerText = statusData.message;

                        if (statusData.status === 'completed') {
                            clearInterval(poll);
                            progressStatus.innerHTML = "<strong>SUCCESS!</strong> Finalizing with Inkscape...";
                            progressFill.style.background = "#4ade80";
                        } else if (statusData.status === 'error') {
                            clearInterval(poll);
                            progressStatus.innerText = "Error: " + statusData.message;
                            submitBtn.disabled = false;
                            submitBtn.innerText = "Generate Vector";
                        }
                    } catch (pollErr) {
                        console.error("Polling error:", pollErr);
                    }
                }, 800);
            } else {
                submitBtn.disabled = false;
                submitBtn.innerText = "Generate Vector";
                statusMsg.innerText = "Startup failed. Check logs.";
            }
        } catch (err) {
            console.error("Submit error:", err);
            submitBtn.disabled = false;
            submitBtn.innerText = "Generate Vector";
            statusMsg.innerText = "Connection error.";
        }
    });

    // Sync Button Placeholder
    syncBtn.addEventListener('click', async () => {
        const provider = providerSelect.value;
        const apiKey = document.getElementById('api_key').value;
        const endpoint = document.getElementById('api_endpoint').value;

        syncBtn.innerText = "Refreshing...";
        syncBtn.disabled = true;
        try {
            const response = await fetch('/sync-models', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider, api_key: apiKey, api_endpoint: endpoint })
            });

            if (response.ok) {
                const data = await response.json();
                const modelSelect = document.getElementById('model');
                modelSelect.innerHTML = '';
                data.models.forEach(m => {
                    const opt = document.createElement('option');
                    opt.value = m;
                    opt.innerText = m;
                    modelSelect.appendChild(opt);
                });
                statusMsg.innerText = "Models updated successfully.";
            } else {
                const errText = await response.text();
                statusMsg.innerText = "Failed to sync models: " + errText;
            }
        } catch (err) {
            console.error(err);
            statusMsg.innerText = "Error connecting to sync service.";
        } finally {
            syncBtn.innerText = "Sync";
            syncBtn.disabled = false;
        }
    });
});
