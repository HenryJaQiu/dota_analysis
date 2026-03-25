const economyChartModes = {};
const PLAYER_CHART_COLORS = [
    "#ff4d4f",
    "#40a9ff",
    "#73d13d",
    "#faad14",
    "#9254de",
    "#13c2c2",
    "#eb2f96",
    "#fa8c16",
    "#a0d911",
    "#2f54eb",
];

function getEconomyChartMode(slot) {
    return economyChartModes[String(slot)] || "all";
}

function setEconomyChartMode(slot, mode, button) {
    economyChartModes[String(slot)] = mode;

    const panel = button?.closest(".chart-container");
    if (panel) {
        panel.querySelectorAll(".chart-mode-btn").forEach(btn => btn.classList.remove("active"));
        button.classList.add("active");
    }

    renderChartsForPlayer(slot);
}

function renderChartsForPlayer(slot) {
    if (!window.MATCH_DATA) return;

    const player = window.MATCH_DATA.players.find(p => String(p.player_slot) === String(slot));
    if (!player) return;

    const container = document.getElementById(`gold-chart-${slot}`);
    const tooltip = document.getElementById(`gold-chart-tooltip-${slot}`);
    const legend = document.getElementById(`gold-chart-legend-${slot}`);
    if (!container || !legend || !tooltip) return;

    const mode = getEconomyChartMode(slot);
    const series = buildEconomySeries(player, mode);
    if (!series.length) return;

    const width = 760;
    const height = 320;
    const padding = { top: 16, right: 16, bottom: 34, left: 58 };
    const innerWidth = width - padding.left - padding.right;
    const innerHeight = height - padding.top - padding.bottom;

    const allPoints = series.flatMap(item => item.points);
    const maxY = Math.max(...allPoints.map(point => point.y), 1);
    const minY = 0;
    const rangeY = Math.max(maxY - minY, 1);
    const maxX = Math.max(...allPoints.map(point => point.x), 1);
    const minuteMarks = buildMinuteMarks(series);

    const scaleX = x => padding.left + (x / maxX) * innerWidth;
    const scaleY = y => padding.top + innerHeight - ((y - minY) / rangeY) * innerHeight;
    const formatGold = value => value >= 1000 ? `${(value / 1000).toFixed(1)}k` : `${value}`;

    const xTicks = buildXTicks(series, maxX).map(value => {
        const x = scaleX(value);
        return `
            <g>
                <line x1="${x}" y1="${padding.top}" x2="${x}" y2="${padding.top + innerHeight}" class="chart-grid-line"></line>
                <text x="${x}" y="${height - 8}" text-anchor="middle" class="chart-axis-label">${value}m</text>
            </g>
        `;
    }).join("");

    const yTicks = [0, 0.25, 0.5, 0.75, 1].map(ratio => {
        const value = Math.round(minY + rangeY * ratio);
        const y = scaleY(value);
        return `
            <g>
                <line x1="${padding.left}" y1="${y}" x2="${padding.left + innerWidth}" y2="${y}" class="chart-grid-line"></line>
                <text x="${padding.left - 8}" y="${y + 4}" text-anchor="end" class="chart-axis-label">${formatGold(value)}</text>
            </g>
        `;
    }).join("");

    const paths = series.map(item => {
        const path = item.points.map((point, index) => {
            const x = scaleX(point.x).toFixed(2);
            const y = scaleY(point.y).toFixed(2);
            return `${index === 0 ? "M" : "L"} ${x} ${y}`;
        }).join(" ");

        return `
            <path
                d="${path}"
                fill="none"
                stroke="${item.color}"
                stroke-opacity="${item.opacity}"
                stroke-width="${item.strokeWidth}"
                stroke-linejoin="round"
                stroke-linecap="round"
            ></path>
        `;
    }).join("");

    const dots = series.map(item =>
        item.points.map(point => {
            const x = scaleX(point.x);
            const y = scaleY(point.y);
            return `
                <circle cx="${x}" cy="${y}" r="${item.highlight ? 3.6 : 2.3}" fill="${item.color}" fill-opacity="${item.opacity}">
                    <title>${item.label} ${point.x} 分钟: ${point.y} 金币</title>
                </circle>
            `;
        }).join("")
    ).join("");

    container.innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" class="gold-chart-svg" role="img" aria-label="${player.hero_name} 经济时间图">
            <rect x="0" y="0" width="${width}" height="${height}" fill="transparent"></rect>
            ${yTicks}
            ${xTicks}
            ${paths}
            ${dots}
            <line id="gold-chart-hover-line-${slot}" x1="${padding.left}" y1="${padding.top}" x2="${padding.left}" y2="${padding.top + innerHeight}" class="chart-hover-line hidden"></line>
        </svg>
    `;

    legend.innerHTML = series.map(item => `
        <div class="chart-legend-item${item.highlight ? " is-highlight" : ""}">
            <span class="chart-legend-swatch" style="background:${item.color}; opacity:${item.opacity};"></span>
            <span class="chart-legend-label">${item.label}</span>
        </div>
    `).join("");

    const svg = container.querySelector("svg");
    const hoverLine = document.getElementById(`gold-chart-hover-line-${slot}`);
    if (!svg || !hoverLine) return;

    const hideTooltip = () => {
        tooltip.classList.add("hidden");
        hoverLine.classList.add("hidden");
    };

    svg.addEventListener("mouseleave", hideTooltip);
    svg.addEventListener("mousemove", event => {
        const rect = svg.getBoundingClientRect();
        const rawX = ((event.clientX - rect.left) / rect.width) * width;
        const clampedX = Math.max(padding.left, Math.min(padding.left + innerWidth, rawX));
        const minute = findNearestMinute(minuteMarks, ((clampedX - padding.left) / innerWidth) * maxX);
        if (minute == null) {
            hideTooltip();
            return;
        }

        const ranking = buildRanking(series, minute);
        const lineX = scaleX(minute);
        hoverLine.setAttribute("x1", lineX);
        hoverLine.setAttribute("x2", lineX);
        hoverLine.classList.remove("hidden");

        tooltip.innerHTML = `
            <div class="chart-tooltip-title">${minute} 分钟</div>
            <div class="chart-tooltip-list">
                ${ranking.map(item => `
                    <div class="chart-tooltip-row ${item.team === "天辉" ? "is-radiant" : item.team === "夜魇" ? "is-dire" : ""}">
                        <span class="chart-tooltip-name">
                            <span class="chart-tooltip-dot" style="background:${item.color};"></span>
                            ${item.label}
                        </span>
                        <span class="chart-tooltip-value">${formatGold(item.value)}</span>
                    </div>
                `).join("")}
            </div>
        `;
        tooltip.classList.remove("hidden");

        const panelRect = container.getBoundingClientRect();
        const tooltipWidth = tooltip.offsetWidth || 180;
        const tooltipHeight = tooltip.offsetHeight || 120;
        let left = ((lineX / width) * panelRect.width) + 12;
        let top = ((padding.top / height) * panelRect.height) + 8;

        if (left + tooltipWidth > panelRect.width - 8) {
            left = ((lineX / width) * panelRect.width) - tooltipWidth - 12;
        }
        if (left < 8) left = 8;
        if (top + tooltipHeight > panelRect.height - 8) {
            top = panelRect.height - tooltipHeight - 8;
        }

        tooltip.style.left = `${left}px`;
        tooltip.style.top = `${top}px`;
    });
}

function buildEconomySeries(selectedPlayer, mode) {
    const players = (window.MATCH_DATA?.players || []).filter(player => {
        const timeline = player.economy?.gold_timeline;
        return Array.isArray(timeline) && timeline.length > 0;
    });

    if (mode === "solo") {
        const points = buildPlayerPoints(selectedPlayer);
        if (!points.length) return [];
        return [{
            ...createSeries(selectedPlayer.hero_name, selectedPlayer.team === "天辉" ? "#4ade80" : "#f87171", points, true, 1),
            team: selectedPlayer.team,
        }];
    }

    if (mode === "teams") {
        const radiantPlayers = players.filter(player => player.team === "天辉");
        const direPlayers = players.filter(player => player.team === "夜魇");
        const radiantPoints = aggregateTeamPoints(radiantPlayers);
        const direPoints = aggregateTeamPoints(direPlayers);
        return [
            { ...createSeries("天辉总经济", "#4ade80", radiantPoints, selectedPlayer.team === "天辉", 0.95), team: "天辉" },
            { ...createSeries("夜魇总经济", "#f87171", direPoints, selectedPlayer.team === "夜魇", 0.95), team: "夜魇" },
        ].filter(item => item.points.length > 0);
    }

    return players.map((player, index) => {
        const points = buildPlayerPoints(player);
        const selected = String(player.player_slot) === String(selectedPlayer.player_slot);
        const baseColor = PLAYER_CHART_COLORS[index % PLAYER_CHART_COLORS.length];
        return {
            ...createSeries(
                player.hero_name,
                baseColor,
                points,
                selected,
                selected ? 1 : 0.7
            ),
            team: player.team,
        };
    }).filter(item => item.points.length > 0);
}

function createSeries(label, color, points, highlight, opacity) {
    return {
        label,
        color,
        points,
        highlight,
        team: null,
        opacity,
        strokeWidth: highlight ? 4 : 2,
    };
}

function buildPlayerPoints(player) {
    const timeline = player.economy?.gold_timeline || [];
    const step = player.economy?.gold_timeline_step || 1;
    return timeline.map((value, index) => ({
        x: index * step,
        y: Number(value),
    }));
}

function aggregateTeamPoints(players) {
    if (!players.length) return [];

    const minuteSet = new Set();
    const playerMaps = players.map(player => {
        const points = buildPlayerPoints(player);
        const map = new Map();
        points.forEach(point => {
            map.set(point.x, point.y);
            minuteSet.add(point.x);
        });
        return map;
    });

    const minutes = Array.from(minuteSet).sort((a, b) => a - b);
    return minutes.map(minute => {
        let total = 0;
        playerMaps.forEach(map => {
            total += getValueAtMinute(map, minute);
        });
        return { x: minute, y: total };
    });
}

function getValueAtMinute(map, minute) {
    if (map.has(minute)) return Number(map.get(minute));

    let lastValue = 0;
    const keys = Array.from(map.keys()).sort((a, b) => a - b);
    for (const key of keys) {
        if (key > minute) break;
        lastValue = Number(map.get(key));
    }
    return lastValue;
}

function buildXTicks(series, maxX) {
    const allMinutes = Array.from(new Set(series.flatMap(item => item.points.map(point => point.x)))).sort((a, b) => a - b);
    if (allMinutes.length <= 8) return allMinutes;

    const step = Math.max(1, Math.ceil(maxX / 6));
    const ticks = [0];
    for (let minute = step; minute < maxX; minute += step) {
        ticks.push(minute);
    }
    if (!ticks.includes(maxX)) ticks.push(maxX);
    return ticks;
}

function buildMinuteMarks(series) {
    return Array.from(new Set(series.flatMap(item => item.points.map(point => point.x)))).sort((a, b) => a - b);
}

function findNearestMinute(minutes, target) {
    if (!minutes.length) return null;
    return minutes.reduce((closest, current) => {
        return Math.abs(current - target) < Math.abs(closest - target) ? current : closest;
    }, minutes[0]);
}

function buildRanking(series, minute) {
    return series.map(item => ({
        label: item.label,
        color: item.color,
        team: item.team,
        value: getSeriesValueAtMinute(item, minute),
        highlight: item.highlight,
    })).sort((a, b) => b.value - a.value);
}

function getSeriesValueAtMinute(series, minute) {
    const pointMap = new Map(series.points.map(point => [point.x, point.y]));
    return getValueAtMinute(pointMap, minute);
}

document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".chart-mode-btn").forEach(button => {
        button.addEventListener("click", function () {
            const slot = this.getAttribute("data-slot");
            const mode = this.getAttribute("data-mode");
            setEconomyChartMode(slot, mode, this);
        });
    });

    const activeTab = document.querySelector(".player-tab.active");
    if (activeTab) {
        const slot = activeTab.getAttribute("data-slot");
        renderChartsForPlayer(slot);
    }
});
