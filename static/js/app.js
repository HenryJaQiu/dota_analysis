function switchPlayer(slot) {
    document.querySelectorAll(".player-tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".player-panel").forEach(p => p.classList.remove("active"));

    const tab = document.querySelector(`[data-slot="${slot}"]`);
    const panel = document.getElementById(`panel-${slot}`);
    if (tab) tab.classList.add("active");
    if (panel) panel.classList.add("active");

    window.location.hash = `player-${slot}`;

    if (window.MATCH_DATA && typeof renderChartsForPlayer === "function") {
        renderChartsForPlayer(slot);
    }
}

function switchSection(btn, sectionId) {
    const panel = btn.closest(".player-panel");
    if (!panel) return;

    panel.querySelectorAll(".section-tab").forEach(t => t.classList.remove("active"));
    panel.querySelectorAll(".section-content").forEach(c => c.classList.remove("active"));

    btn.classList.add("active");
    const section = document.getElementById(sectionId);
    if (section) section.classList.add("active");

    if (sectionId.startsWith("economy-") && typeof renderChartsForPlayer === "function") {
        const slot = sectionId.replace("economy-", "");
        renderChartsForPlayer(slot);
    }
}

const analyzeForm = document.getElementById("analyze-form");
let pollTimer = null;

function renderJobProgress(job) {
    const panel = document.getElementById("job-progress");
    if (!panel) return;

    const statusTextMap = {
        idle: "等待开始",
        queued: "排队中",
        running: "分析中",
        completed: "已完成",
        failed: "失败",
    };

    panel.classList.remove("hidden");
    panel.className = `job-progress status-${job.status}`;
    panel.innerHTML = `
        <div class="job-progress-head">
            <div>
                <div class="job-progress-title">比赛 #${job.match_id}</div>
                <div class="job-progress-status">${statusTextMap[job.status] || job.status}</div>
            </div>
            ${job.redirect_url ? `<a href="${job.redirect_url}" class="job-progress-link">查看详情</a>` : ""}
        </div>
        <div class="job-progress-message">${job.message || ""}</div>
        ${job.error ? `<div class="job-progress-error">${job.error}</div>` : ""}
    `;
}

async function pollJob(matchId) {
    try {
        const response = await fetch(`/api/jobs/${matchId}`);
        const job = await response.json();
        if (!response.ok && response.status !== 404) {
            throw new Error(job.error || "获取任务状态失败");
        }

        renderJobProgress(job);

        if (job.status === "completed") {
            localStorage.removeItem("activeMatchJob");
            if (pollTimer) clearInterval(pollTimer);
            pollTimer = null;
            if (job.redirect_url) {
                window.location.href = job.redirect_url;
            }
            return;
        }

        if (job.status === "failed") {
            localStorage.removeItem("activeMatchJob");
            if (pollTimer) clearInterval(pollTimer);
            pollTimer = null;
        }
    } catch (error) {
        console.error(error);
    }
}

function startPolling(matchId) {
    if (!matchId) return;
    if (pollTimer) clearInterval(pollTimer);
    pollJob(matchId);
    pollTimer = setInterval(() => pollJob(matchId), 2000);
}

if (analyzeForm) {
    analyzeForm.addEventListener("submit", async function (event) {
        event.preventDefault();

        const submitBtn = document.getElementById("submit-btn");
        const btnText = submitBtn?.querySelector(".btn-text");
        const btnLoading = submitBtn?.querySelector(".btn-loading");
        const formData = new FormData(analyzeForm);

        if (submitBtn) submitBtn.disabled = true;
        if (btnText) btnText.classList.add("hidden");
        if (btnLoading) btnLoading.classList.remove("hidden");

        try {
            const response = await fetch("/analyze", {
                method: "POST",
                body: formData,
            });
            const payload = await response.json();

            if (!response.ok || !payload.ok) {
                throw new Error(payload.error || "提交分析任务失败");
            }

            localStorage.setItem("activeMatchJob", String(payload.match_id));
            renderJobProgress(payload);
            startPolling(payload.match_id);
        } catch (error) {
            const panel = document.getElementById("job-progress");
            if (panel) {
                panel.classList.remove("hidden");
                panel.className = "job-progress status-failed";
                panel.innerHTML = `<div class="job-progress-error">${error.message}</div>`;
            }
        } finally {
            if (submitBtn) submitBtn.disabled = false;
            if (btnText) btnText.classList.remove("hidden");
            if (btnLoading) btnLoading.classList.add("hidden");
        }
    });
}

function initReanalysis() {
    const btn = document.getElementById("reanalyze-btn");
    const panel = document.getElementById("reanalyze-status");
    if (!btn || !panel) return;

    const matchId = btn.dataset.matchId;
    let timer = null;
    let reloadTimer = null;

    const setBusy = (busy) => {
        btn.disabled = busy;
        btn.textContent = busy ? "生成中…" : "用当前模型重新生成建议";
    };

    const render = (job) => {
        const statusLabels = {
            idle: "等待开始",
            queued: "排队中",
            running: "生成中",
            completed: "已完成",
            failed: "失败",
        };
        panel.classList.remove("hidden");
        panel.className = `job-progress status-${job.status || "idle"}`;
        panel.textContent = "";

        const head = document.createElement("div");
        head.className = "job-progress-head";

        const titleWrap = document.createElement("div");
        const title = document.createElement("div");
        title.className = "job-progress-title";
        title.textContent = `比赛 #${matchId} · AI 建议`;
        const status = document.createElement("div");
        status.className = "job-progress-status";
        status.textContent = statusLabels[job.status] || job.status || "";
        titleWrap.appendChild(title);
        titleWrap.appendChild(status);
        head.appendChild(titleWrap);
        panel.appendChild(head);

        const message = document.createElement("div");
        message.className = "job-progress-message";
        message.textContent = job.message || "";
        panel.appendChild(message);

        if (job.error) {
            const error = document.createElement("div");
            error.className = "job-progress-error";
            error.textContent = job.error;
            panel.appendChild(error);
        }
    };

    const stopPolling = () => {
        if (timer) clearInterval(timer);
        timer = null;
    };

    const poll = async () => {
        try {
            const response = await fetch(`/api/match/${matchId}/reanalyze`, { cache: "no-store" });
            const job = await response.json();
            if (!response.ok) throw new Error(job.error || job.detail || "获取状态失败");
            render(job);

            if (job.status === "completed") {
                stopPolling();
                setBusy(false);
                if (reloadTimer) clearTimeout(reloadTimer);
                reloadTimer = setTimeout(() => window.location.reload(), 900);
            } else if (job.status === "failed" || job.status === "idle") {
                stopPolling();
                setBusy(false);
            }
        } catch (error) {
            console.error(error);
            stopPolling();
            setBusy(false);
        }
    };

    const startPolling = () => {
        stopPolling();
        poll();
        timer = setInterval(poll, 2500);
    };

    btn.addEventListener("click", async () => {
        setBusy(true);
        try {
            const response = await fetch(`/api/match/${matchId}/reanalyze`, { method: "POST" });
            const job = await response.json();
            if (!response.ok) {
                throw new Error(job.error || job.detail || "启动重新生成失败");
            }
            render(job);
            startPolling();
        } catch (error) {
            setBusy(false);
            panel.classList.remove("hidden");
            panel.className = "job-progress status-failed";
            panel.textContent = "";
            const message = document.createElement("div");
            message.className = "job-progress-error";
            message.textContent = error.message;
            panel.appendChild(message);
        }
    });

    // Resume the status display if a reanalysis job survived a page refresh.
    fetch(`/api/match/${matchId}/reanalyze`, { cache: "no-store" })
        .then((response) => response.json())
        .then((job) => {
            if (job.status === "running" || job.status === "queued") {
                setBusy(true);
                render(job);
                startPolling();
            } else if (job.status === "failed") {
                render(job);
            }
        })
        .catch(() => {});
}

function initParseWatcher() {
    const box = document.getElementById("parse-watch");
    if (!box) return;

    const matchId = box.dataset.matchId;
    const message = document.getElementById("parse-status-message");
    const retry = document.getElementById("parse-retry-btn");
    let timer = null;

    const setMessage = (text) => {
        if (message) message.textContent = text;
    };
    const stop = () => {
        if (timer) clearInterval(timer);
        timer = null;
    };
    const setRetry = (enabled) => {
        if (retry) retry.disabled = !enabled;
    };

    const poll = async () => {
        try {
            const response = await fetch(`/api/match/${matchId}/parse`, { cache: "no-store" });
            const job = await response.json();
            if (!response.ok) {
                throw new Error(job.error || job.detail || "获取解析状态失败");
            }

            if (job.ready) {
                stop();
                setRetry(false);
                setMessage("录像解析完成，正在刷新页面…");
                setTimeout(() => window.location.reload(), 700);
                return;
            }

            if (job.status === "running" || job.status === "queued") {
                setRetry(false);
                setMessage(job.message || "正在等待录像解析…");
            } else if (job.status === "failed") {
                stop();
                setRetry(true);
                setMessage(job.error || "录像仍未解析完成，稍后刷新页面会自动重试。");
            } else if (job.status === "completed") {
                stop();
                setRetry(true);
                setMessage(job.message || "解析任务已结束，但数据尚未更新，请刷新页面重试。");
            } else if (job.status === "idle") {
                stop();
                setRetry(true);
                setMessage("解析任务尚未启动，可点击「重新检查解析」。");
            }
        } catch (error) {
            console.error(error);
            stop();
            setRetry(true);
            setMessage(`获取解析状态失败：${error.message}`);
        }
    };

    const start = () => {
        stop();
        poll();
        timer = setInterval(poll, 3000);
    };

    retry?.addEventListener("click", async () => {
        setRetry(false);
        setMessage("正在重新提交解析请求…");
        try {
            const response = await fetch(`/api/match/${matchId}/parse`, { method: "POST" });
            const job = await response.json();
            if (!response.ok) {
                throw new Error(job.error || job.detail || "启动解析失败");
            }
            start();
        } catch (error) {
            setRetry(true);
            setMessage(`重新检查失败：${error.message}`);
        }
    });

    start();
}

document.addEventListener("DOMContentLoaded", function () {
    const queryMatchId = new URLSearchParams(window.location.search).get("match_id");
    const activeJob = localStorage.getItem("activeMatchJob");
    const matchId = queryMatchId || activeJob;
    if (matchId && document.getElementById("job-progress")) {
        startPolling(matchId);
    }

    initReanalysis();
    initParseWatcher();

    const hash = window.location.hash;
    if (hash && hash.startsWith("#player-")) {
        const slot = hash.replace("#player-", "");
        switchPlayer(slot);
    }
});
