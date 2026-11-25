(function () {
    "use strict";

    const section = document.getElementById("follow-section");
    if (!section) return;

    const listEl = document.getElementById("follow-list");
    const statusEl = document.getElementById("follow-status");
    const form = document.getElementById("follow-form");
    const input = document.getElementById("follow-input");
    const nicknameInput = document.getElementById("follow-nickname");
    const submitBtn = document.getElementById("follow-submit");
    const refreshBtn = document.getElementById("follow-refresh-btn");

    function setStatus(message, type) {
        statusEl.textContent = message || "";
        statusEl.className = "follow-status" + (type ? ` is-${type}` : "");
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

    function makeAvatar(player) {
        if (player.avatar && /^https?:\/\//i.test(player.avatar)) {
            const img = document.createElement("img");
            img.className = "follow-avatar";
            img.src = player.avatar;
            img.alt = "";
            img.loading = "lazy";
            img.referrerPolicy = "no-referrer";
            img.onerror = () => {
                const fallback = document.createElement("div");
                fallback.className = "follow-avatar follow-avatar-fallback";
                fallback.textContent = (player.personaname || "?").slice(0, 1).toUpperCase();
                img.replaceWith(fallback);
            };
            return img;
        }
        const fallback = document.createElement("div");
        fallback.className = "follow-avatar follow-avatar-fallback";
        fallback.textContent = (player.personaname || "?").slice(0, 1).toUpperCase();
        return fallback;
    }

    function makeMatchRow(match) {
        const link = document.createElement("a");
        link.className = "follow-match";
        link.href = `/match/${match.match_id}`;
        link.title = `比赛 #${match.match_id}${match.played_at ? ` · ${match.played_at}` : ""}`;

        const hero = document.createElement("span");
        hero.className = "fm-hero";
        hero.textContent = match.hero_name || `英雄#${match.hero_id || "?"}`;
        link.appendChild(hero);

        const matchId = document.createElement("span");
        matchId.className = "fm-id";
        matchId.textContent = `#${match.match_id}`;
        link.appendChild(matchId);

        const result = document.createElement("span");
        result.className = `fm-result ${match.won ? "win" : "loss"}`;
        result.textContent = match.result || (match.won ? "胜" : "负");
        link.appendChild(result);

        const kda = document.createElement("span");
        kda.className = "fm-kda";
        kda.textContent = `${match.kills}/${match.deaths}/${match.assists}`;
        link.appendChild(kda);

        if (match.duration_minutes) {
            const duration = document.createElement("span");
            duration.className = "fm-duration";
            duration.textContent = `${match.duration_minutes}m`;
            link.appendChild(duration);
        }

        const time = document.createElement("span");
        time.className = "fm-time";
        time.textContent = match.time_ago || "";
        link.appendChild(time);

        if (match.analyzed) {
            const cached = document.createElement("span");
            cached.className = "fm-cached";
            cached.textContent = "已分析";
            link.appendChild(cached);
        }

        return link;
    }

    function makeCard(player) {
        const card = document.createElement("article");
        card.className = "follow-card";

        const head = document.createElement("div");
        head.className = "follow-card-head";
        head.appendChild(makeAvatar(player));

        const identity = document.createElement("div");
        identity.className = "follow-identity";

        const name = document.createElement("div");
        name.className = "follow-name";
        name.textContent = player.personaname || `玩家 ${player.account_id}`;
        if (player.nickname && player.nickname !== player.personaname) {
            const nick = document.createElement("span");
            nick.className = "follow-nick";
            nick.textContent = `备注：${player.nickname}`;
            name.appendChild(nick);
        }
        identity.appendChild(name);

        const meta = document.createElement("div");
        meta.className = "follow-meta";
        meta.textContent = `ID ${player.account_id} · ${player.steam_id64 || ""}`;
        identity.appendChild(meta);
        head.appendChild(identity);

        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "follow-remove";
        remove.dataset.followRemove = String(player.account_id);
        remove.dataset.followName = player.personaname || `玩家 ${player.account_id}`;
        remove.textContent = "取消关注";
        head.appendChild(remove);
        card.appendChild(head);

        if (player.error) {
            const error = document.createElement("div");
            error.className = "follow-error";
            error.textContent = `最近一次刷新失败：${player.error}`;
            card.appendChild(error);
        }

        const matches = document.createElement("div");
        matches.className = "follow-matches";
        if (!player.matches || !player.matches.length) {
            const empty = document.createElement("div");
            empty.className = "follow-empty";
            empty.textContent = "暂无最近公开比赛";
            matches.appendChild(empty);
        } else {
            player.matches.forEach((match) => matches.appendChild(makeMatchRow(match)));
        }
        card.appendChild(matches);

        const updated = document.createElement("div");
        updated.className = "follow-updated";
        updated.textContent = `更新于 ${player.updated_text || "尚未更新"}`;
        card.appendChild(updated);

        return card;
    }

    function render(data) {
        const players = (data && data.players) || [];
        listEl.innerHTML = "";
        if (!players.length) {
            const empty = document.createElement("div");
            empty.className = "follow-empty";
            empty.textContent = "还没有关注玩家。输入 Steam 好友 ID 即可开始。";
            listEl.appendChild(empty);
            return;
        }
        players.forEach((player) => listEl.appendChild(makeCard(player)));
    }

    async function refreshFollows(force, auto) {
        refreshBtn.disabled = true;
        setStatus(auto ? "正在自动更新关注玩家的最近比赛…" : "正在刷新关注玩家的最近比赛…");
        try {
            const response = await fetch(
                `/api/follows/refresh?force=${force ? "1" : "0"}`,
                { method: "POST" }
            );
            const data = await readJson(response);
            render(data);
            const errors = data.errors || [];
            if (errors.length) {
                setStatus(
                    `已更新 ${data.refreshed || 0} 位玩家，${errors.length} 位刷新失败：${errors[0].error}`,
                    "warning"
                );
            } else if (data.refreshed) {
                setStatus(`已更新 ${data.refreshed} 位玩家的最近比赛`, "success");
            } else {
                setStatus(auto ? "关注列表已是最新" : "暂时没有需要更新的玩家");
            }
        } catch (error) {
            setStatus(`刷新失败：${error.message}`, "error");
        } finally {
            refreshBtn.disabled = false;
        }
    }

    async function loadFollows() {
        try {
            const response = await fetch("/api/follows", { cache: "no-store" });
            const data = await readJson(response);
            render(data);
            if (data.needs_refresh && (data.players || []).length) {
                refreshFollows(false, true);
            }
        } catch (error) {
            setStatus(`读取关注列表失败：${error.message}`, "error");
            listEl.innerHTML = "";
            const empty = document.createElement("div");
            empty.className = "follow-empty";
            empty.textContent = "关注列表暂时不可用";
            listEl.appendChild(empty);
        }
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const steamId = input.value.trim();
        const nickname = nicknameInput.value.trim();
        if (!steamId) {
            setStatus("请先填写 Steam 好友 ID 或 SteamID64", "error");
            input.focus();
            return;
        }

        submitBtn.disabled = true;
        setStatus("正在解析玩家并获取最近比赛…");
        try {
            const response = await fetch("/api/follows", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ steam_id: steamId, nickname }),
            });
            const data = await readJson(response);
            render(data);
            const added = data.added || {};
            setStatus(`已关注 ${added.personaname || steamId}`, "success");
            input.value = "";
            nicknameInput.value = "";
        } catch (error) {
            setStatus(`关注失败：${error.message}`, "error");
        } finally {
            submitBtn.disabled = false;
        }
    });

    listEl.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-follow-remove]");
        if (!button) return;
        const accountId = button.dataset.followRemove;
        const name = button.dataset.followName || accountId;
        if (!window.confirm(`确定取消关注 ${name} 吗？`)) return;

        button.disabled = true;
        setStatus(`正在取消关注 ${name}…`);
        try {
            const response = await fetch(`/api/follows/${accountId}`, { method: "DELETE" });
            const data = await readJson(response);
            render(data);
            setStatus(`已取消关注 ${name}`, "success");
        } catch (error) {
            button.disabled = false;
            setStatus(`取消关注失败：${error.message}`, "error");
        }
    });

    refreshBtn.addEventListener("click", () => refreshFollows(true, false));

    loadFollows();
})();
