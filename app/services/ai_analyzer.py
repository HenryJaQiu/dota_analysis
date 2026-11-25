"""Provider-agnostic AI coach that turns match stats into Chinese review tips."""

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.analysis import AISuggestions, MatchAnalysis, PlayerAnalysis
from app.services.llm_client import LLMError, chat_completion, new_session_id
from app.services.llm_settings import LLMConfig, get_llm_config

logger = logging.getLogger(__name__)

LIST_FIELDS = (
    "economy_tips",
    "teamfight_tips",
    "item_tips",
    "vision_tips",
    "laning_tips",
)


class AIAnalyzer:
    SYSTEM_PROMPT = """你是一位专业的 Dota 2 教练，正在分析比赛录像数据。你的职责是根据玩家的统计数据给出具体、可执行的改进建议。你熟悉英雄定位、出装方案、经济理论、视野控制和团战走位。

请严格按照以下 JSON 格式回复，不要包含 Markdown 代码块或任何其他内容：
{
  "economy_tips": ["建议1", "建议2"],
  "teamfight_tips": ["建议1", "建议2"],
  "item_tips": ["建议1", "建议2"],
  "vision_tips": ["建议1"],
  "laning_tips": ["建议1"],
  "overall_summary": "2-3句总体表现概述",
  "priority_improvement": "这名玩家最应该优先改进的一点"
}

要求：
- 针对所玩英雄给出具体建议，不要泛泛而谈
- 引用实际数据（如具体数字）
- 每个分类 1-3 条建议
- 如果某维度数据不可用（null），跳过或简短说明
- 使用中文回复"""

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or get_llm_config()
        self._semaphore = asyncio.Semaphore(max(1, self.config.concurrency))

    @property
    def model_label(self) -> str:
        return f"{self.config.provider}/{self.config.model}"

    def _session_id(self, match_id: int) -> str:
        return new_session_id(
            f"dota-review:{match_id}:{self.config.provider}:{self.config.model}"
        )

    async def analyze_player(
        self, player: PlayerAnalysis, match: MatchAnalysis
    ) -> AISuggestions:
        async with self._semaphore:
            prompt = self._build_prompt(player, match)
            try:
                text = await chat_completion(
                    self.config,
                    self.SYSTEM_PROMPT,
                    prompt,
                    max_tokens=self.config.max_tokens,
                    session_id=self._session_id(match.match_id),
                )
                suggestions = parse_ai_response(text)
                suggestions.provider = self.config.provider
                suggestions.model = self.config.model
                suggestions.generated_at = datetime.utcnow()
                return suggestions
            except LLMError as exc:
                logger.warning(
                    "AI review failed for %s with %s: %s",
                    player.hero_name,
                    self.model_label,
                    exc.message,
                )
                return self._error_suggestions(exc.message)
            except Exception as exc:
                logger.exception("Unexpected AI review error for %s", player.hero_name)
                return self._error_suggestions(f"AI 分析失败：{str(exc)[:160]}")

    def _error_suggestions(self, message: str) -> AISuggestions:
        return AISuggestions(
            error=message[:300],
            provider=self.config.provider,
            model=self.config.model,
            generated_at=datetime.utcnow(),
        )

    async def analyze_all_players(self, match: MatchAnalysis) -> MatchAnalysis:
        if not self.config.configured:
            if self.config.requires_key and not self.config.api_key:
                message = "尚未配置模型 API Key，请在页面右上角「模型设置」中填写"
            else:
                message = "尚未配置可用的 AI 模型，请在「模型设置」中完善 Base URL 与模型名称"
            for player in match.players:
                player.ai_suggestions = self._error_suggestions(message)
            return match

        logger.info(
            "Generating AI reviews for match %s with %s (%s)",
            match.match_id,
            self.model_label,
            self.config.base_url,
        )
        tasks = [self.analyze_player(player, match) for player in match.players]
        suggestions = await asyncio.gather(*tasks, return_exceptions=True)
        for i, suggestion in enumerate(suggestions):
            if isinstance(suggestion, Exception):
                match.players[i].ai_suggestions = self._error_suggestions(
                    f"AI 分析失败：{str(suggestion)[:160]}"
                )
            else:
                match.players[i].ai_suggestions = suggestion

        failed = sum(1 for p in match.players if p.ai_suggestions and p.ai_suggestions.error)
        if failed:
            logger.warning("%s/%s player reviews failed", failed, len(match.players))
        return match

    def _build_prompt(self, player: PlayerAnalysis, match: MatchAnalysis) -> str:
        same_team = [
            p.hero_name
            for p in match.players
            if p.team == player.team and p.hero_name != player.hero_name
        ]
        enemy_team = [p.hero_name for p in match.players if p.team != player.team]
        result = "胜利" if (player.team == "天辉") == match.radiant_win else "失败"
        duration = f"{match.duration_minutes:.1f}"

        lines = [
            "【比赛信息】",
            f"时长: {duration} 分钟 | {player.team} {result}",
            f"友方阵容: {player.hero_name}, {', '.join(same_team)}",
            f"敌方阵容: {', '.join(enemy_team)}",
            "",
            "【玩家信息】",
            f"玩家: {player.personaname or '匿名'} | 英雄: {player.hero_name} | 段位: {player.rank_name}",
            "",
            "【经济 & 补刀】",
            f"GPM: {player.economy.gpm}",
            f"XPM: {player.economy.xpm}",
            f"补刀/反补: {player.economy.last_hits}/{player.economy.denies}",
            f"净身价: {player.economy.net_worth}",
            f"花费金钱: {player.economy.gold_spent}",
        ]

        if player.economy.gpm_benchmark_pct is not None:
            lines.append(f"GPM 同英雄百分位: {player.economy.gpm_benchmark_pct}%")
        if player.economy.lh_benchmark_pct is not None:
            lines.append(f"补刀百分位: {player.economy.lh_benchmark_pct}%")
        if player.economy.gold_timeline:
            lines.append(f"经济时间线(每5分钟): {player.economy.gold_timeline}")

        tf = player.teamfight
        lines += [
            "",
            "【团战表现】",
            f"KDA: {tf.kills}/{tf.deaths}/{tf.assists} (评分: {tf.kda})",
            f"英雄伤害: {tf.hero_damage}",
            f"防御塔伤害: {tf.tower_damage}",
            f"治疗量: {tf.hero_healing}",
        ]
        if tf.hero_damage_benchmark_pct is not None:
            lines.append(f"伤害百分位: {tf.hero_damage_benchmark_pct}%")
        if tf.participation_rate is not None:
            lines.append(f"团战参与率: {tf.participation_rate:.0%}")

        items = player.items
        lines += [
            "",
            "【出装】",
            f"最终装备: {', '.join(items.final_items) or '无'}",
            f"神杖: {'是' if items.aghanims_scepter else '否'} | 魔晶: {'是' if items.aghanims_shard else '否'} | 月煞: {'是' if items.moonshard else '否'}",
        ]
        if items.has_timeline and items.purchase_timeline:
            timeline_str = " → ".join(
                f"{entry['time_str']} {entry['item']}" for entry in items.purchase_timeline[:8]
            )
            lines.append(f"购买记录: {timeline_str}")

        vision = player.vision
        if vision.available:
            lines += [
                "",
                "【视野控制】",
                f"真眼放置: {vision.obs_placed} | 哨戒眼放置: {vision.sen_placed}",
                f"摧毁敌方真眼: {vision.obs_killed}",
            ]
        else:
            lines.append("\n【视野控制】数据需解析录像后获取")

        laning = player.laning
        if laning.available:
            lines += [
                "",
                "【对线 & 野区】",
                f"对线位置: {laning.lane_name or '未知'} | 游走: {'是' if laning.is_roaming else '否'}",
                f"叠营数: {laning.camps_stacked}",
                f"操作频率(APM): {laning.actions_per_min}",
            ]
        else:
            lines.append("\n【对线 & 野区】数据需解析录像后获取")

        obj = player.objectives
        if obj.available:
            lines += [
                "",
                "【目标控制】",
                f"参与击杀肉山: {obj.roshan_kills}次",
                f"参与击杀痛苦魔方: {obj.tormentor_kills}次",
                f"拾取智慧神符: {obj.wisdom_runes}次",
            ]

        lines.append("\n请根据以上数据提供教练建议（只输出 JSON）:")
        return "\n".join(lines)


def strip_thinking(text: str) -> str:
    text = text or ""
    for pattern in (
        r"<think(?:ing)?>.*?</think(?:ing)?>",
        r"<\|?think\|?>.*?<\|?/think\|?>",
        r"\[(?:thinking|think)\].*?\[/(?:thinking|think)\]",
        r"```(?:thinking|think)\s*\n.*?```",
    ):
        text = re.sub(pattern, "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def _coerce_text(value: Any, limit: int = 2000) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = "；".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()[:limit]


def _coerce_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [value.strip()] if value.strip() else []
    elif isinstance(value, (list, tuple, set)):
        parts = [str(item).strip() for item in value if str(item).strip()]
    else:
        parts = [str(value).strip()]
    return [part[:600] for part in parts if part][:6]


def _normalize_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for field in LIST_FIELDS:
        normalized[field] = _coerce_list(data.get(field))

    normalized["overall_summary"] = _coerce_text(
        data.get("overall_summary") or data.get("summary")
    )
    normalized["priority_improvement"] = _coerce_text(
        data.get("priority_improvement") or data.get("priority") or data.get("key_advice"),
        limit=1000,
    )
    return normalized


def _loads_json(candidate: str) -> Optional[Dict[str, Any]]:
    candidate = candidate.strip()
    if not candidate:
        return None
    for text in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
        try:
            data = json.loads(text)
        except Exception:
            continue
        if isinstance(data, dict):
            return data
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
    return None


def parse_ai_response(text: str) -> AISuggestions:
    cleaned = strip_thinking(text)
    if not cleaned:
        return AISuggestions(
            overall_summary="模型没有返回可用内容",
            error="模型返回为空",
        )

    data = _loads_json(cleaned)
    if data is None:
        for block in re.findall(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.DOTALL | re.IGNORECASE):
            data = _loads_json(block)
            if data is not None:
                break

    if data is None:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end > start:
            data = _loads_json(cleaned[start : end + 1])

    if data is not None:
        return AISuggestions(**_normalize_payload(data))

    return AISuggestions(
        overall_summary=cleaned[:1200],
        error="模型没有按 JSON 格式返回，以下为原始回复",
    )
