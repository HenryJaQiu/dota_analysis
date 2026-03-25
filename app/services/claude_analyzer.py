import asyncio
import json
import logging
import re
from typing import Optional

from openai import OpenAI

from app.config import settings
from app.models.analysis import PlayerAnalysis, AISuggestions, MatchAnalysis

logger = logging.getLogger(__name__)


class ClaudeAnalyzer:
    SYSTEM_PROMPT = """你是一位专业的 Dota 2 教练，正在分析比赛录像数据。你的职责是根据玩家的统计数据给出具体、可执行的改进建议。你熟悉英雄定位、出装方案、经济理论、视野控制和团战走位。

请严格按照以下 JSON 格式回复，不要包含任何其他内容：
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

    def __init__(self):
        self._client = OpenAI(
            api_key=settings.minimax_api_key,
            base_url=settings.minimax_base_url,
        )
        self._semaphore = asyncio.Semaphore(3)

    async def analyze_player(
        self, player: PlayerAnalysis, match: MatchAnalysis
    ) -> AISuggestions:
        async with self._semaphore:
            try:
                prompt = self._build_prompt(player, match)
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._client.chat.completions.create(
                        model=settings.minimax_model,
                        max_tokens=settings.ai_max_tokens,
                        messages=[
                            {"role": "system", "content": self.SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                    ),
                )
                text = response.choices[0].message.content
                return self._parse_response(text)
            except Exception as e:
                logger.error(f"MiniMax analysis failed for {player.hero_name}: {e}")
                return AISuggestions(
                    overall_summary=f"AI 分析暂不可用: {str(e)[:100]}",
                    priority_improvement="请检查 API Key 配置",
                )

    async def analyze_all_players(self, match: MatchAnalysis) -> MatchAnalysis:
        tasks = [self.analyze_player(p, match) for p in match.players]
        suggestions = await asyncio.gather(*tasks, return_exceptions=True)
        for i, sug in enumerate(suggestions):
            if isinstance(sug, Exception):
                match.players[i].ai_suggestions = AISuggestions(
                    overall_summary="AI 分析失败",
                    priority_improvement="请稍后重试",
                )
            else:
                match.players[i].ai_suggestions = sug
        return match

    def _build_prompt(self, player: PlayerAnalysis, match: MatchAnalysis) -> str:
        same_team = [p.hero_name for p in match.players if p.team == player.team and p.hero_name != player.hero_name]
        enemy_team = [p.hero_name for p in match.players if p.team != player.team]
        result = "胜利" if (player.team == "天辉") == match.radiant_win else "失败"
        duration = f"{match.duration_minutes:.1f}"

        lines = [
            f"【比赛信息】",
            f"时长: {duration} 分钟 | {player.team} {result}",
            f"友方阵容: {player.hero_name}, {', '.join(same_team)}",
            f"敌方阵容: {', '.join(enemy_team)}",
            f"",
            f"【玩家信息】",
            f"玩家: {player.personaname or '匿名'} | 英雄: {player.hero_name} | 段位: {player.rank_name}",
            f"",
            f"【经济 & 补刀】",
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
            f"",
            f"【团战表现】",
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
            f"",
            f"【出装】",
            f"最终装备: {', '.join(items.final_items) or '无'}",
            f"神杖: {'是' if items.aghanims_scepter else '否'} | 魔晶: {'是' if items.aghanims_shard else '否'} | 月煞: {'是' if items.moonshard else '否'}",
        ]
        if items.has_timeline and items.purchase_timeline:
            timeline_str = " → ".join(
                f"{e['time_str']} {e['item']}" for e in items.purchase_timeline[:8]
            )
            lines.append(f"购买记录: {timeline_str}")

        vision = player.vision
        if vision.available:
            lines += [
                f"",
                f"【视野控制】",
                f"真眼放置: {vision.obs_placed} | 哨戒眼放置: {vision.sen_placed}",
                f"摧毁敌方真眼: {vision.obs_killed}",
            ]
        else:
            lines.append(f"\n【视野控制】数据需解析录像后获取")

        laning = player.laning
        if laning.available:
            lines += [
                f"",
                f"【对线 & 野区】",
                f"对线位置: {laning.lane_name or '未知'} | 游走: {'是' if laning.is_roaming else '否'}",
                f"叠营数: {laning.camps_stacked}",
                f"操作频率(APM): {laning.actions_per_min}",
            ]
        else:
            lines.append(f"\n【对线 & 野区】数据需解析录像后获取")

        obj = player.objectives
        if obj.available:
            lines += [
                f"",
                f"【目标控制】",
                f"参与击杀肉山: {obj.roshan_kills}次",
                f"参与击杀痛苦魔方: {obj.tormentor_kills}次",
                f"拾取智慧神符: {obj.wisdom_runes}次",
            ]

        lines.append("\n请根据以上数据提供教练建议（JSON格式）:")
        return "\n".join(lines)

    def _strip_thinking(self, text: str) -> str:
        """Remove <think>...</think> reasoning blocks from MiniMax-M2.7 responses."""
        return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

    def _parse_response(self, text: str) -> AISuggestions:
        text = self._strip_thinking(text)
        try:
            data = json.loads(text.strip())
            return AISuggestions(**data)
        except Exception:
            pass

        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                return AISuggestions(**data)
            except Exception:
                pass

        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                return AISuggestions(**data)
            except Exception:
                pass

        return AISuggestions(
            overall_summary=text[:500] if text else "无法解析 AI 回复",
            priority_improvement="请查看完整回复",
        )


_analyzer: Optional[ClaudeAnalyzer] = None


def get_analyzer() -> ClaudeAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = ClaudeAnalyzer()
    return _analyzer
