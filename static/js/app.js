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

document.addEventListener("DOMContentLoaded", function () {
    const queryMatchId = new URLSearchParams(window.location.search).get("match_id");
    const activeJob = localStorage.getItem("activeMatchJob");
    const matchId = queryMatchId || activeJob;
    if (matchId && document.getElementById("job-progress")) {
        startPolling(matchId);
    }

    const hash = window.location.hash;
    if (hash && hash.startsWith("#player-")) {
        const slot = hash.replace("#player-", "");
        switchPlayer(slot);
    }
});
