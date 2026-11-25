import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.models.match import ParseStatus
from app.services.ai_analyzer import AIAnalyzer
from app.services.analysis_jobs import (
    KIND_ANALYSIS,
    KIND_PARSE,
    KIND_REANALYZE,
    get_job_manager,
)
from app.services.cache import get_cache
from app.services.data_processor import DataProcessor
from app.services.llm_settings import get_llm_config, public_settings
from app.services.opendota import MatchNotFoundError, OpenDotaAPIError, get_client
from app.services.verdict import build_match_verdict
from app.utils.hero_names import get_hero_map
from app.utils.item_names import get_item_map

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    cache = get_cache()
    recent = cache.list_recent(20)
    return templates.TemplateResponse(request, "index.html", {
        "recent": recent,
        "error": None,
        "llm": public_settings(),
    })


@router.post("/analyze")
async def analyze_match(match_id: str = Form(...)):
    match_id_str = match_id.strip()
    if not match_id_str.isdigit():
        return JSONResponse({
            "ok": False,
            "error": "请输入有效的数字比赛 ID",
        }, status_code=400)

    mid = int(match_id_str)
    cache = get_cache()
    cached = cache.get(mid)
    jobs = get_job_manager()

    if cached:
        if cached.parse_status != ParseStatus.PARSED:
            await _ensure_parse_job(mid)
            return JSONResponse({
                "ok": True,
                "match_id": mid,
                "status": "completed",
                "message": "已加载本地基础数据，正在后台等待录像解析",
                "redirect_url": f"/match/{mid}",
                "parse_status": cached.parse_status.value,
            })

        return JSONResponse({
            "ok": True,
            "match_id": mid,
            "status": "completed",
            "message": "分析结果已存在本地，可在详情页用当前模型重新生成 AI 建议",
            "redirect_url": f"/match/{mid}",
            "parse_status": cached.parse_status.value,
        })

    job = await jobs.start_job(mid, _run_analysis_job)
    return JSONResponse({
        "ok": True,
        "match_id": mid,
        "status": job["status"],
        "message": job["message"],
        "redirect_url": job["result_url"],
    }, status_code=202)


@router.get("/match/{match_id}", response_class=HTMLResponse)
async def get_match(request: Request, match_id: int):
    cache = get_cache()
    cached = cache.get(match_id)
    if cached:
        parse_refreshing = False
        if cached.parse_status != ParseStatus.PARSED:
            job = await _ensure_parse_job(match_id)
            parse_refreshing = bool(
                job and job["status"] in {"queued", "running"}
            )
        else:
            _ensure_verdict(cached, cache, match_id)

        ai_model = next(
            (
                player.ai_suggestions.model
                for player in cached.players
                if player.ai_suggestions and player.ai_suggestions.model
            ),
            None,
        )

        return templates.TemplateResponse(request, "match.html", {
            "analysis": cached,
            "from_cache": True,
            "parse_refreshing": parse_refreshing,
            "ai_model": ai_model,
            "llm": public_settings(),
        })

    await get_job_manager().start_job(match_id, _run_analysis_job)
    return RedirectResponse(url=f"/?match_id={match_id}")


def _ensure_verdict(analysis, cache, match_id: int) -> None:
    if analysis.parse_status != ParseStatus.PARSED or analysis.verdict is not None:
        return
    verdict = build_match_verdict(analysis)
    if verdict:
        analysis.verdict = verdict
        cache.set(match_id, analysis)


async def _ensure_parse_job(match_id: int) -> Optional[dict]:
    cache = get_cache()
    cached = cache.get(match_id)
    if not cached or cached.parse_status == ParseStatus.PARSED:
        return None
    return await get_job_manager().start_job(
        match_id, _run_parse_wait_job, kind=KIND_PARSE
    )


def _ai_failure_message(analysis) -> str:
    failed = sum(
        1
        for player in analysis.players
        if player.ai_suggestions and player.ai_suggestions.error
    )
    model = get_llm_config().model
    if failed == len(analysis.players):
        return "分析完成，但 AI 建议全部生成失败，请检查「模型设置」"
    if failed:
        return f"分析完成，{failed} 名玩家的 AI 建议生成失败"
    return f"分析完成（AI: {model}）"


async def _run_analysis_job(match_id: int) -> None:
    jobs = get_job_manager()
    cache = get_cache()

    if cache.get(match_id):
        await jobs.mark_completed(match_id, "分析结果已存在本地")
        return

    try:
        await jobs.mark_running(match_id, "正在获取比赛数据")
        client = get_client()
        raw_match = await client.fetch_match(match_id)
        cache.save_raw(match_id, raw_match)
        parse_status = client.detect_parse_status(raw_match)

        if parse_status != ParseStatus.PARSED:
            # Show useful basic data immediately, then wait in the background.
            analysis = await _process_match(
                match_id,
                raw_match,
                parse_status,
                jobs,
                generate_ai=False,
                kind=KIND_ANALYSIS,
            )
            cache.set(match_id, analysis)
            await jobs.mark_completed(
                match_id,
                "基础数据已生成，正在后台等待录像解析",
            )
            await _ensure_parse_job(match_id)
            return

        analysis = await _process_match(
            match_id,
            raw_match,
            parse_status,
            jobs,
            generate_ai=True,
            kind=KIND_ANALYSIS,
        )
        cache.set(match_id, analysis)
        await jobs.mark_completed(match_id, _ai_failure_message(analysis))
    except MatchNotFoundError:
        await jobs.mark_failed(match_id, "未找到该比赛，请检查比赛 ID")
    except OpenDotaAPIError as e:
        await jobs.mark_failed(match_id, f"OpenDota 接口暂时不可用: {e}")
    except Exception as e:
        logger.exception("Unexpected error analyzing match %s", match_id)
        await jobs.mark_failed(match_id, f"分析失败: {str(e)}")


async def _run_parse_wait_job(match_id: int) -> None:
    jobs = get_job_manager()
    cache = get_cache()
    cached = cache.get(match_id)
    if not cached:
        await jobs.mark_failed(
            match_id,
            "该比赛还没有基础数据，请先完成比赛分析",
            kind=KIND_PARSE,
        )
        return
    if cached.parse_status == ParseStatus.PARSED:
        await jobs.mark_completed(
            match_id,
            "录像已经解析完成",
            kind=KIND_PARSE,
        )
        return

    client = get_client()
    try:
        await jobs.mark_running(match_id, "正在检查录像解析状态", kind=KIND_PARSE)
        raw_match = await client.fetch_match(match_id)
        cache.save_raw(match_id, raw_match)
        parse_status = client.detect_parse_status(raw_match)

        if parse_status != ParseStatus.PARSED:
            await jobs.set_progress(
                match_id,
                "已提交解析请求，等待 OpenDota 解析录像",
                kind=KIND_PARSE,
            )

            async def on_progress(attempt: int, total: int) -> None:
                await jobs.set_progress(
                    match_id,
                    f"正在等待 OpenDota 解析录像（{attempt}/{total}）",
                    kind=KIND_PARSE,
                )

            raw_match, parse_status = await client.wait_for_parse(
                match_id, on_progress=on_progress
            )
            cache.save_raw(match_id, raw_match)

        if parse_status != ParseStatus.PARSED:
            await jobs.mark_failed(
                match_id,
                "录像仍未解析完成，已保留基础数据；稍后刷新页面会自动重试",
                kind=KIND_PARSE,
            )
            return

        await jobs.set_progress(
            match_id,
            "录像解析完成，正在整理完整数据",
            kind=KIND_PARSE,
        )
        analysis = await _process_match(
            match_id,
            raw_match,
            parse_status,
            jobs,
            generate_ai=True,
            kind=KIND_PARSE,
        )
        cache.set(match_id, analysis)

        message = "录像解析完成，已升级为完整数据"
        failed = sum(
            1
            for player in analysis.players
            if player.ai_suggestions and player.ai_suggestions.error
        )
        if failed == len(analysis.players):
            message += "，但 AI 建议生成失败，请检查「模型设置」"
        elif failed:
            message += f"（{failed} 名玩家的 AI 建议失败）"
        await jobs.mark_completed(match_id, message, kind=KIND_PARSE)
    except MatchNotFoundError:
        await jobs.mark_failed(
            match_id, "未找到该比赛，无法检查录像解析状态", kind=KIND_PARSE
        )
    except OpenDotaAPIError as e:
        await jobs.mark_failed(
            match_id, f"OpenDota 接口暂时不可用: {e}", kind=KIND_PARSE
        )
    except Exception as e:
        logger.exception("Parse wait failed for match %s", match_id)
        await jobs.mark_failed(
            match_id, f"等待录像解析失败: {str(e)[:200]}", kind=KIND_PARSE
        )


async def _process_match(
    match_id: int,
    raw_match,
    parse_status: ParseStatus,
    jobs,
    *,
    generate_ai: bool,
    kind: str,
):
    client = get_client()
    await jobs.set_progress(match_id, "正在加载英雄与道具映射", kind=kind)
    hero_map, item_map = await _load_maps(client)

    await jobs.set_progress(match_id, "正在整理比赛数据", kind=kind)
    processor = DataProcessor(hero_map, item_map)
    analysis = processor.process_match(raw_match, parse_status)

    if generate_ai:
        config = get_llm_config()
        await jobs.set_progress(
            match_id,
            f"正在用 {config.model} 生成 AI 复盘建议",
            kind=kind,
        )
        analyzer = AIAnalyzer(config)
        analysis = await analyzer.analyze_all_players(analysis)
    return analysis


async def _load_maps(client):
    hero_task = get_hero_map(client)
    item_task = get_item_map(client)
    return await asyncio.gather(hero_task, item_task)


@router.get("/api/jobs/{match_id}")
async def match_job_status(match_id: int):
    cache = get_cache()
    cached = cache.get(match_id)
    if cached:
        job = await get_job_manager().get_job(match_id, KIND_ANALYSIS)
        if job and job["status"] in {"queued", "running"}:
            return JSONResponse(job)
        return JSONResponse({
            "match_id": match_id,
            "status": "completed",
            "message": "分析完成",
            "redirect_url": f"/match/{match_id}",
            "parse_status": cached.parse_status.value,
        })

    job = await get_job_manager().get_job(match_id, KIND_ANALYSIS)
    if not job:
        return JSONResponse({
            "match_id": match_id,
            "status": "idle",
            "message": "未找到任务",
            "redirect_url": f"/match/{match_id}",
        }, status_code=404)

    return JSONResponse(job)


@router.get("/api/match/{match_id}/parse")
async def parse_status(match_id: int):
    cache = get_cache()
    cached = cache.get(match_id)
    job = await get_job_manager().get_job(match_id, KIND_PARSE)
    ready = bool(cached and cached.parse_status == ParseStatus.PARSED)

    if ready:
        return JSONResponse({
            "match_id": match_id,
            "status": "completed",
            "message": "录像解析完成",
            "parse_status": ParseStatus.PARSED.value,
            "ready": True,
            "error": None,
        })

    return JSONResponse({
        "match_id": match_id,
        "status": job["status"] if job else "idle",
        "message": job["message"] if job else "尚未开始解析",
        "parse_status": cached.parse_status.value if cached else None,
        "ready": False,
        "error": job["error"] if job else None,
    })


@router.post("/api/match/{match_id}/parse")
async def retry_parse(match_id: int):
    cache = get_cache()
    cached = cache.get(match_id)
    if not cached:
        return JSONResponse(
            {"error": "该比赛还没有基础数据，请先完成比赛分析"},
            status_code=404,
        )
    if cached.parse_status == ParseStatus.PARSED:
        return JSONResponse({
            "match_id": match_id,
            "status": "completed",
            "message": "录像已经解析完成",
            "parse_status": ParseStatus.PARSED.value,
            "ready": True,
        })

    job = await _ensure_parse_job(match_id)
    if not job:
        return JSONResponse({
            "match_id": match_id,
            "status": "idle",
            "message": "暂时无法启动解析任务",
        }, status_code=409)
    return JSONResponse(job, status_code=202)


@router.post("/api/match/{match_id}/reanalyze")
async def start_reanalysis(match_id: int):
    cached = get_cache().get(match_id)
    if not cached:
        return JSONResponse(
            {"error": "该比赛还没有分析缓存，请先完成比赛分析"},
            status_code=404,
        )

    jobs = get_job_manager()
    active_analysis = await jobs.get_job(match_id, KIND_ANALYSIS)
    if active_analysis and active_analysis["status"] in {"queued", "running"}:
        return JSONResponse(
            {"error": "该比赛正在分析中，请等待分析完成后再重新生成 AI 建议"},
            status_code=409,
        )

    active_parse = await jobs.get_job(match_id, KIND_PARSE)
    if active_parse and active_parse["status"] in {"queued", "running"}:
        return JSONResponse(
            {"error": "正在等待录像解析，解析完成后会自动生成 AI 建议"},
            status_code=409,
        )

    config = get_llm_config()
    if not config.configured:
        return JSONResponse(
            {"error": "尚未配置可用的 AI 模型，请先在「模型设置」中填写 API Key 与模型"},
            status_code=400,
        )

    job = await jobs.start_job(
        match_id, _run_reanalysis_job, kind=KIND_REANALYZE
    )
    return JSONResponse(job, status_code=202)


@router.get("/api/match/{match_id}/reanalyze")
async def reanalysis_status(match_id: int):
    job = await get_job_manager().get_job(match_id, KIND_REANALYZE)
    if not job:
        return JSONResponse({
            "match_id": match_id,
            "kind": KIND_REANALYZE,
            "status": "idle",
            "message": "尚未发起重新生成",
        })
    return JSONResponse(job)


async def _run_reanalysis_job(match_id: int) -> None:
    jobs = get_job_manager()
    cache = get_cache()
    original: Optional = cache.get(match_id)
    if not original:
        await jobs.mark_failed(
            match_id,
            "该比赛还没有分析缓存，请先完成比赛分析",
            kind=KIND_REANALYZE,
        )
        return

    if original.parse_status != ParseStatus.PARSED:
        active_parse = await jobs.get_job(match_id, KIND_PARSE)
        if active_parse and active_parse["status"] in {"queued", "running"}:
            await jobs.mark_failed(
                match_id,
                "正在等待录像解析，解析完成后会自动生成 AI 建议",
                kind=KIND_REANALYZE,
            )
            return

    config = get_llm_config()
    if not config.configured:
        await jobs.mark_failed(
            match_id,
            "尚未配置可用的 AI 模型，请先在「模型设置」中填写",
            kind=KIND_REANALYZE,
        )
        return

    try:
        await jobs.mark_running(
            match_id,
            f"正在用 {config.model} 重新生成 AI 建议",
            kind=KIND_REANALYZE,
        )
        working = original.model_copy(deep=True)
        analyzer = AIAnalyzer(config)
        updated = await analyzer.analyze_all_players(working)

        failures = sum(
            1
            for player in updated.players
            if player.ai_suggestions and player.ai_suggestions.error
        )
        if failures == len(updated.players):
            await jobs.mark_failed(
                match_id,
                "AI 建议全部生成失败，已保留原有建议，请检查模型设置",
                kind=KIND_REANALYZE,
            )
            return

        cache.set(match_id, updated)
        message = f"AI 建议已用 {config.model} 更新"
        if failures:
            message += f"（{failures} 名玩家失败）"
        await jobs.mark_completed(match_id, message, kind=KIND_REANALYZE)
    except Exception as exc:
        logger.exception("Reanalysis failed for match %s", match_id)
        await jobs.mark_failed(
            match_id,
            f"重新生成失败: {str(exc)[:200]}",
            kind=KIND_REANALYZE,
        )


@router.get("/api/match/{match_id}/data")
async def match_data_api(match_id: int):
    cache = get_cache()
    analysis = cache.get(match_id)
    if not analysis:
        return JSONResponse({"error": "Not found"}, status_code=404)
    _ensure_verdict(analysis, cache, match_id)
    return JSONResponse({"analysis": analysis.model_dump(mode="json")})
