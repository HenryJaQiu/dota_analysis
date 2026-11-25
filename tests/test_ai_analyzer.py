from app.services.ai_analyzer import parse_ai_response, strip_thinking


def test_parses_plain_json():
    text = """
    {
      "economy_tips": ["多补 20 个刀"],
      "teamfight_tips": ["先手前等队友"],
      "item_tips": ["跳刀提前 3 分钟"],
      "vision_tips": [],
      "laning_tips": ["不要越塔"],
      "overall_summary": "整体表现稳定。",
      "priority_improvement": "提高中期刷钱效率。"
    }
    """
    result = parse_ai_response(text)
    assert result.economy_tips == ["多补 20 个刀"]
    assert result.priority_improvement == "提高中期刷钱效率。"
    assert result.error is None


def test_parses_fenced_json_and_strips_thinking():
    text = """
    <think>先分析数据，再给建议。</think>
    ```json
    {"economy_tips": "补刀偏低", "overall_summary": "需要加强发育"}
    ```
    """
    result = parse_ai_response(text)
    assert result.economy_tips == ["补刀偏低"]
    assert "先分析" not in result.overall_summary


def test_coerces_string_and_ignores_unknown_fields():
    text = """
    {"teamfight_tips": "多参加团战", "unknown_field": 1,
     "overall_summary": ["第一行", "第二行"]}
    """
    result = parse_ai_response(text)
    assert result.teamfight_tips == ["多参加团战"]
    assert "第一行" in result.overall_summary
    assert result.item_tips == []


def test_unparseable_text_falls_back_to_summary():
    result = parse_ai_response("这是一段没有 JSON 的普通回复。")
    assert result.overall_summary == "这是一段没有 JSON 的普通回复。"
    assert result.error


def test_strip_thinking_variants():
    assert strip_thinking("<thinking>abc</thinking>结果") == "结果"
    assert strip_thinking("前缀<think>abc</think>后缀") == "前缀后缀"
