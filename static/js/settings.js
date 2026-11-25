(function () {
    "use strict";

    const state = {
        settings: null,
        presets: {},
        modelProtocols: {},
        loading: false,
        lastProvider: null,
    };

    const $ = (id) => document.getElementById(id);

    function escapeHtml(value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    async function readJson(response) {
        let data = null;
        try {
            data = await response.json();
        } catch (error) {
            data = null;
        }
        if (!response.ok) {
            let detail = data && (data.detail || data.error);
            if (Array.isArray(detail)) {
                detail = detail.map((item) => item.msg || JSON.stringify(item)).join("；");
            }
            throw new Error(detail || `请求失败（${response.status}）`);
        }
        return data;
    }

    function setStatus(message, type) {
        const node = $("llm-settings-status");
        if (!node) return;
        node.textContent = message || "";
        node.className = "settings-status" + (type ? ` is-${type}` : "");
    }

    function presetFor(providerId) {
        return state.presets[providerId] || null;
    }

    function applySettingsToPage(settings) {
        if (!settings) return;

        document.querySelectorAll(".js-llm-model").forEach((node) => {
            node.textContent = settings.model || "未选择模型";
        });
        document.querySelectorAll(".js-llm-provider").forEach((node) => {
            node.textContent = settings.provider_label || "";
        });
        document.querySelectorAll(".js-llm-warning").forEach((node) => {
            node.classList.toggle("hidden", !!settings.configured);
        });

        const chip = $("header-model-chip");
        if (chip) {
            const label = settings.model
                ? `${settings.provider_label} · ${settings.model}`
                : "未选择模型 · 点击设置";
            chip.textContent = label;
            chip.classList.toggle("is-warning", !settings.configured);
            chip.title = settings.configured
                ? "当前 AI 模型，点击修改"
                : "尚未配置可用的模型，点击设置";
        }
    }

    function buildProviderOptions(providers) {
        const select = $("llm-provider");
        if (!select) return;
        select.innerHTML = "";
        providers.forEach((provider) => {
            const option = document.createElement("option");
            option.value = provider.id;
            option.textContent = provider.label;
            select.appendChild(option);
        });
    }

    function updateProviderHint(providerId, settings) {
        const preset = presetFor(providerId);
        const hint = $("llm-provider-hint");
        const keyHint = $("llm-key-hint");
        if (!preset) return;

        if (hint) {
            hint.innerHTML = escapeHtml(preset.description || "");
            if (preset.docs_url) {
                hint.innerHTML += ` <a href="${escapeHtml(preset.docs_url)}" target="_blank" rel="noopener noreferrer">获取 Key</a>`;
            }
        }

        if (keyHint) {
            let text = preset.key_hint || "";
            if (settings && settings.api_key_set && settings.provider === providerId) {
                text += ` 已保存：${settings.api_key_masked}（留空则不修改）`;
            }
            keyHint.textContent = text;
        }
    }

    function fillForm(settings) {
        if (!settings) return;
        buildProviderOptions(settings.providers || []);

        $("llm-provider").value = settings.provider;
        $("llm-base-url").value = settings.base_url || "";
        $("llm-model").value = settings.model || "";
        $("llm-protocol").value = settings.protocol || "auto";
        $("llm-temperature").value = settings.temperature;
        $("llm-max-tokens").value = settings.max_tokens;
        $("llm-timeout").value = settings.timeout;
        $("llm-concurrency").value = settings.concurrency;

        const keyInput = $("llm-api-key");
        keyInput.value = "";
        keyInput.type = "password";
        $("llm-toggle-key").textContent = "显示";
        keyInput.placeholder = settings.api_key_masked
            ? `已保存：${settings.api_key_masked}（留空则不修改）`
            : "粘贴 API Key";

        state.lastProvider = settings.provider;
        updateProviderHint(settings.provider, settings);

        const modelHint = $("llm-model-hint");
        if (modelHint) {
            modelHint.textContent = settings.model
                ? `当前模型：${settings.model}`
                : "可直接手动输入模型 ID，或从服务端拉取模型列表。";
        }
    }

    async function fetchSettings() {
        const response = await fetch("/api/llm/settings", { cache: "no-store" });
        const settings = await readJson(response);
        state.settings = settings;
        state.presets = {};
        (settings.providers || []).forEach((provider) => {
            state.presets[provider.id] = provider;
        });
        applySettingsToPage(settings);
        return settings;
    }

    async function openModal() {
        const modal = $("settings-modal");
        if (!modal) return;

        modal.classList.add("open");
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("modal-open");
        setStatus("");

        if (!state.settings) {
            try {
                await fetchSettings();
            } catch (error) {
                setStatus(`读取设置失败：${error.message}`, "error");
            }
        }
        if (state.settings) {
            fillForm(state.settings);
        }
        const provider = $("llm-provider");
        if (provider) provider.focus();
    }

    function closeModal() {
        const modal = $("settings-modal");
        if (!modal) return;
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
        document.body.classList.remove("modal-open");
    }

    function collectPayload() {
        return {
            provider: $("llm-provider").value,
            base_url: $("llm-base-url").value.trim(),
            api_key: $("llm-api-key").value.trim(),
            model: $("llm-model").value.trim(),
            protocol: $("llm-protocol").value,
            temperature: parseFloat($("llm-temperature").value),
            max_tokens: parseInt($("llm-max-tokens").value, 10),
            timeout: parseInt($("llm-timeout").value, 10),
            concurrency: parseInt($("llm-concurrency").value, 10),
        };
    }

    function validatePayload(payload) {
        if (!payload.base_url || !payload.base_url.startsWith("http")) {
            throw new Error("请填写以 http:// 或 https:// 开头的 Base URL");
        }
        if (!payload.model) {
            throw new Error("请填写模型名称");
        }
        if (Number.isNaN(payload.temperature) || Number.isNaN(payload.max_tokens)
            || Number.isNaN(payload.timeout) || Number.isNaN(payload.concurrency)) {
            throw new Error("请填写有效的数值参数");
        }
    }

    async function saveSettings() {
        const button = $("llm-save");
        const payload = collectPayload();
        try {
            validatePayload(payload);
        } catch (error) {
            setStatus(error.message, "error");
            return;
        }

        button.disabled = true;
        setStatus("正在保存…");
        try {
            const response = await fetch("/api/llm/settings", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const settings = await readJson(response);
            state.settings = settings;
            state.presets = {};
            (settings.providers || []).forEach((provider) => {
                state.presets[provider.id] = provider;
            });
            applySettingsToPage(settings);
            fillForm(settings);
            setStatus("设置已保存，可以关闭窗口开始分析。", "success");
        } catch (error) {
            setStatus(error.message, "error");
        } finally {
            button.disabled = false;
        }
    }

    async function testConnection() {
        const button = $("llm-test");
        const payload = collectPayload();
        try {
            validatePayload(payload);
        } catch (error) {
            setStatus(error.message, "error");
            return;
        }

        button.disabled = true;
        setStatus("正在连接模型服务…");
        try {
            const response = await fetch("/api/llm/test", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    provider: payload.provider,
                    base_url: payload.base_url,
                    api_key: payload.api_key,
                    model: payload.model,
                    protocol: payload.protocol,
                }),
            });
            const result = await readJson(response);
            const reply = (result.reply || "").replace(/\s+/g, " ").slice(0, 60);
            setStatus(
                `连接成功 · ${result.latency_ms} ms · ${result.protocol} 协议 · 模型 ${result.model} · 回复：${reply}`,
                "success"
            );
        } catch (error) {
            setStatus(`连接失败：${error.message}`, "error");
        } finally {
            button.disabled = false;
        }
    }

    async function refreshModels() {
        const button = $("llm-refresh-models");
        const baseUrl = $("llm-base-url").value.trim();
        if (!baseUrl) {
            setStatus("请先填写 Base URL", "error");
            return;
        }

        const params = new URLSearchParams({
            base_url: baseUrl,
            protocol: $("llm-protocol").value,
            provider: $("llm-provider").value,
        });
        const typedKey = $("llm-api-key").value.trim();
        if (typedKey) params.set("api_key", typedKey);

        button.disabled = true;
        button.textContent = "拉取中…";
        const hint = $("llm-model-hint");
        if (hint) hint.textContent = "正在从模型服务拉取列表…";

        try {
            const response = await fetch(`/api/llm/models?${params.toString()}`, { cache: "no-store" });
            const result = await readJson(response);
            const datalist = $("llm-model-options");
            datalist.innerHTML = "";
            state.modelProtocols = {};
            (result.models || []).forEach((model) => {
                state.modelProtocols[model.id] = model.protocol || "auto";
                const option = document.createElement("option");
                option.value = model.id;
                option.label = model.name && model.name !== model.id
                    ? `${model.name}（${model.id}）`
                    : model.id;
                datalist.appendChild(option);
            });

            const count = (result.models || []).length;
            if (hint) {
                const source = result.source === "remote" ? "远程接口" : "预设列表";
                const skipped = result.skipped
                    ? `，已忽略 ${result.skipped} 个不支持的类型`
                    : "";
                hint.textContent = `已获取 ${count} 个可用模型（${source}，${result.resolved_protocol} 协议${skipped}）。可输入关键字筛选或直接手动填写。`;
                hint.classList.toggle("is-warning", result.source !== "remote");
            }
            if (result.warning) {
                setStatus(result.warning, "warning");
            } else {
                setStatus(`模型列表已更新，共 ${count} 个。`, "success");
            }
        } catch (error) {
            if (hint) {
                hint.textContent = "拉取失败，可直接手动输入模型 ID。";
                hint.classList.add("is-warning");
            }
            setStatus(error.message, "error");
        } finally {
            button.disabled = false;
            button.textContent = "拉取列表";
        }
    }

    async function clearKey() {
        if (!state.settings || !state.settings.api_key_set) {
            setStatus("当前没有已保存的 API Key。", "warning");
            return;
        }
        if (!window.confirm("确定要清除本机保存的 API Key 吗？")) return;

        try {
            const response = await fetch("/api/llm/settings/clear-key", { method: "POST" });
            const settings = await readJson(response);
            state.settings = settings;
            applySettingsToPage(settings);
            fillForm(settings);
            setStatus("API Key 已清除。", "success");
        } catch (error) {
            setStatus(error.message, "error");
        }
    }

    function wireEvents() {
        document.addEventListener("click", (event) => {
            const opener = event.target.closest("[data-open-settings]");
            if (opener) {
                event.preventDefault();
                openModal();
            }
        });

        const modal = $("settings-modal");
        if (modal) {
            modal.addEventListener("mousedown", (event) => {
                if (event.target === modal) closeModal();
            });
        }
        $("settings-close")?.addEventListener("click", closeModal);
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && modal && modal.classList.contains("open")) {
                closeModal();
            }
        });

        $("llm-toggle-key")?.addEventListener("click", () => {
            const input = $("llm-api-key");
            const button = $("llm-toggle-key");
            const show = input.type === "password";
            input.type = show ? "text" : "password";
            button.textContent = show ? "隐藏" : "显示";
        });

        $("llm-provider")?.addEventListener("change", (event) => {
            const providerId = event.target.value;
            const preset = presetFor(providerId);
            if (!preset) return;

            $("llm-base-url").value = preset.base_url || "";
            $("llm-model").value = preset.default_model || "";
            $("llm-protocol").value = preset.protocol || "auto";
            $("llm-model-options").innerHTML = "";
            state.lastProvider = providerId;
            updateProviderHint(providerId, state.settings);

            const sameProvider = state.settings && state.settings.provider === providerId;
            const keyInput = $("llm-api-key");
            keyInput.value = "";
            if (sameProvider && state.settings.api_key_set) {
                keyInput.placeholder = `已保存：${state.settings.api_key_masked}（留空则不修改）`;
            } else {
                keyInput.placeholder = preset.requires_key
                    ? "切换来源后需重新填写 API Key"
                    : "本地服务可留空";
            }

            const modelHint = $("llm-model-hint");
            if (modelHint) modelHint.textContent = "已切换到预设模型，可点击「拉取列表」或手动修改。";
        });

        $("llm-refresh-models")?.addEventListener("click", refreshModels);

        $("llm-model")?.addEventListener("change", () => {
            const modelId = $("llm-model").value.trim();
            const protocol = state.modelProtocols[modelId];
            if (!protocol || protocol === "auto") return;
            $("llm-protocol").value = protocol;
            const hint = $("llm-model-hint");
            if (hint) {
                hint.textContent = `已选择 ${modelId}，自动使用 ${protocol} 协议。`;
                hint.classList.remove("is-warning");
            }
        });

        $("llm-save")?.addEventListener("click", saveSettings);
        $("llm-test")?.addEventListener("click", testConnection);
        $("llm-clear-key")?.addEventListener("click", clearKey);
    }

    async function init() {
        wireEvents();
        try {
            await fetchSettings();
        } catch (error) {
            console.warn("无法加载模型设置", error);
            const chip = $("header-model-chip");
            if (chip) {
                chip.textContent = "模型设置不可用";
                chip.classList.add("is-warning");
            }
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
