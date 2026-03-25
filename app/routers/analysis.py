import asyncio
import logging
from functools import partial

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.models.match import ParseStatus
from app.services.analysis_jobs import get_job_manager
from app.services.cache import get_cache
from app.services.claude_analyzer import get_analyzer
from app.services.data_processor import DataProcessor
from app.services.opendota import OpenDotaAPIError, MatchNotFoundError, get_client
from app.utils.hero_names import get_hero_map
from app.utils.item_names import get_item_map

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    cache = get_cache()
    recent = cache.list_recent(5)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "recent": recent,
        "error": None,
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
            job = await jobs.start_job(mid, partial(_run_analysis_job, force_refresh=True))
            return JSONResponse({
                "ok": True,
                "match_id": mid,
                "status": job["status"],
                "message": "已存在基础数据，正在后台检查录像是否解析完成",
                "redirect_url": f"/match/{mid}",
            }, status_code=202)

        return JSONResponse({
            "ok": True,
            "match_id": mid,
            "status": "completed",
            "message": "分析结果已存在缓存",
            "redirect_url": f"/match/{mid}",
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
            await get_job_manager().start_job(match_id, partial(_run_analysis_job, force_refresh=True))
            parse_refreshing = True

        return templates.TemplateResponse("match.html", {
            "request": request,
            "analysis": cached,
            "from_cache": True,
            "parse_refreshing": parse_refreshing,
        })

    await get_job_manager().start_job(match_id, _run_analysis_job)
    return RedirectResponse(url=f"/?match_id={match_id}")


async def _run_analysis_job(match_id: int, force_refresh: bool = False) -> None:
    jobs = get_job_manager()
    cache = get_cache()
    cached = cache.get(match_id)

    if cached and not force_refresh:
        await jobs.mark_completed(match_id)
        return

    if cached and force_refresh and cached.parse_status == ParseStatus.PARSED:
        await jobs.mark_completed(match_id)
        return

    try:
        await jobs.mark_running(match_id, "正在获取比赛数据")
        analysis = await _build_analysis(match_id, jobs, wait_for_parse=not force_refresh)
        if analysis is None:
            await jobs.mark_completed(match_id, "录像仍未解析完成，已保留当前基础数据")
            return

        cache.set(match_id, analysis)
        if force_refresh:
            await jobs.mark_completed(match_id, "录像已解析完成，缓存已更新")
        else:
            await jobs.mark_completed(match_id)
    except MatchNotFoundError:
        await jobs.mark_failed(match_id, "未找到该比赛，请检查比赛 ID")
    except OpenDotaAPIError as e:
        await jobs.mark_failed(match_id, f"OpenDota 接口暂时不可用: {e}")
    except Exception as e:
        logger.exception("Unexpected error analyzing match %s", match_id)
        await jobs.mark_failed(match_id, f"分析失败: {str(e)}")


async def _build_analysis(match_id: int, jobs, wait_for_parse: bool):
    client = get_client()

    await jobs.set_progress(match_id, "正在从 OpenDota 拉取比赛信息")
    raw_match = await client.fetch_match(match_id)
    parse_status = client.detect_parse_status(raw_match)

    if parse_status == ParseStatus.NOT_PARSED:
        if wait_for_parse:
            await jobs.set_progress(match_id, "比赛录像未解析，已提交解析请求")
            raw_match, parse_status = await client.wait_for_parse(match_id)
        else:
            return None

    await jobs.set_progress(match_id, "正在加载英雄与道具映射")
    hero_map, item_map = await _load_maps(client)

    await jobs.set_progress(match_id, "正在整理比赛数据")
    processor = DataProcessor(hero_map, item_map)
    analysis = processor.process_match(raw_match, parse_status)

    await jobs.set_progress(match_id, "正在生成 AI 复盘建议")
    analyzer = get_analyzer()
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
        return JSONResponse({
            "match_id": match_id,
            "status": "completed",
            "message": "分析完成",
            "redirect_url": f"/match/{match_id}",
            "parse_status": cached.parse_status.value,
        })

    job = await get_job_manager().get_job(match_id)
    if not job:
        return JSONResponse({
            "match_id": match_id,
            "status": "idle",
            "message": "未找到任务",
            "redirect_url": f"/match/{match_id}",
        }, status_code=404)

    return JSONResponse(job)


@router.get("/api/match/{match_id}/data")
async def match_data_api(match_id: int):
    cache = get_cache()
    analysis = cache.get(match_id)
    if not analysis:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse({"analysis": analysis.dict()})
