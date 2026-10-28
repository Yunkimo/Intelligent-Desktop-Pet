"""视觉识别层测试：纯函数（data URL / 消息构造 / JSON 提取 / 周数解析）与解析流程（mock 上游）。"""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from app import config, vision

GRID_COURSE = {
    "name": "数学",
    "day_of_week": 3,
    "start_time": "08:00",
    "end_time": "09:40",
    "location": "A101",
    "teacher": "",
    "weeks": [1, 2, 3],
}


def test_to_data_url_roundtrip():
    data_url = vision.to_data_url(b"fake-image", "image/jpeg")
    assert data_url.startswith("data:image/jpeg;base64,")
    import base64

    assert base64.b64decode(data_url.split(",", 1)[1]) == b"fake-image"


def test_build_messages_structure():
    messages = vision.build_messages(b"fake-image", "image/jpeg")
    assert messages[0] == {"role": "system", "content": vision.VISION_SYSTEM_PROMPT}
    user_content = messages[1]["content"]
    assert user_content[0]["type"] == "image_url"
    assert user_content[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert user_content[1]["type"] == "text"


def test_extract_json_object_plain():
    assert vision.extract_json_object('{"a": 1}') == {"a": 1}


def test_extract_json_object_code_fence():
    assert vision.extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_object_prose_around():
    text = '识别结果如下：{"grid": [], "notes": []} 以上。'
    assert vision.extract_json_object(text) == {"grid": [], "notes": []}


def test_extract_json_object_invalid_json_raises():
    with pytest.raises(vision.VisionError):
        vision.extract_json_object("{broken json}")


def test_extract_json_object_empty_raises():
    with pytest.raises(vision.VisionError):
        vision.extract_json_object("")


def test_extract_json_object_array_raises():
    with pytest.raises(vision.VisionError):
        vision.extract_json_object("[1, 2]")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1-16", list(range(1, 17))),
        ("1-9,12-18", [*range(1, 10), *range(12, 19)]),
        ("1-9/12-18", [*range(1, 10), *range(12, 19)]),
        ("11-18(单周)", [11, 13, 15, 17]),
        ("2-18双周", [2, 4, 6, 8, 10, 12, 14, 16, 18]),
        ("7,11周", [7, 11]),
        (5, [5]),
        ([1, 2], [1, 2]),
        ("abc", None),
        (None, None),
    ],
)
def test_coerce_weeks_variants(raw, expected):
    assert vision._coerce_weeks(raw) == expected


def test_parse_image_unconfigured_raises(monkeypatch):
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(config, "LLM_VISION_MODEL", "Qwen/Qwen3-VL-32B-Instruct")

    async def scenario():
        mocked = AsyncMock()
        monkeypatch.setattr(vision, "_call_vision", mocked)
        with pytest.raises(vision.VisionNotConfigured):
            await vision.parse_schedule_image(b"img", "image/jpeg")
        mocked.assert_not_awaited()

    asyncio.run(scenario())


def test_parse_image_normalizes_and_drops_invalid(monkeypatch):
    monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(config, "LLM_VISION_MODEL", "Qwen/Qwen3-VL-32B-Instruct")

    async def scenario():
        payload = {
            "grid": [
                {
                    "name": "数学",
                    "day_of_week": "3",
                    "start_time": "8:00",
                    "end_time": "9:40",
                    "location": "A101",
                    "teacher": "王老师",
                    "weeks": "1-16",
                },
                {"name": None, "day_of_week": 9},
            ],
            "notes": [],
        }
        monkeypatch.setattr(
            vision,
            "_call_vision",
            AsyncMock(side_effect=[json.dumps(payload), json.dumps(payload)]),
        )
        result = await vision.parse_schedule_image(b"img", "image/jpeg")
        assert result["skipped"] == 2  # 两轮各 1 条无效
        assert len(result["courses"]) == 1
        course = result["courses"][0]
        assert course["name"] == "数学"
        assert course["day_of_week"] == 3
        assert course["start_time"] == "08:00"
        assert course["end_time"] == "09:40"
        assert course["location"] == "A101"
        assert course["teacher"] == "王老师"
        assert course["weeks"] == list(range(1, 17))

    asyncio.run(scenario())


def test_parse_image_dedupes_duplicates(monkeypatch):
    monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(config, "LLM_VISION_MODEL", "Qwen/Qwen3-VL-32B-Instruct")

    async def scenario():
        payload = {"grid": [GRID_COURSE, GRID_COURSE, GRID_COURSE], "notes": []}
        monkeypatch.setattr(
            vision,
            "_call_vision",
            AsyncMock(side_effect=[json.dumps(payload), json.dumps(payload)]),
        )
        result = await vision.parse_schedule_image(b"img", "image/jpeg")
        assert len(result["courses"]) == 1
        assert result["skipped"] == 4  # 两轮各去重 2 条

    asyncio.run(scenario())


def test_parse_image_merges_notes_and_skips_unmatched(monkeypatch):
    monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(config, "LLM_VISION_MODEL", "Qwen/Qwen3-VL-32B-Instruct")

    async def scenario():
        # 数学有格子但缺教师/周次 → 备注补齐；体育只有备注无格子 → 跳过不臆造
        payload = {
            "grid": [{**GRID_COURSE, "weeks": None}],
            "notes": [
                {"name": "数学", "teacher": "王老师", "weeks": "1-16"},
                {"name": "体育课外测试", "teacher": "李老师", "weeks": "1-9,12-18"},
            ],
        }
        monkeypatch.setattr(
            vision,
            "_call_vision",
            AsyncMock(side_effect=[json.dumps(payload), json.dumps(payload)]),
        )
        result = await vision.parse_schedule_image(b"img", "image/jpeg")
        assert len(result["courses"]) == 1
        assert result["courses"][0]["teacher"] == "王老师"
        assert result["courses"][0]["weeks"] == list(range(1, 17))
        assert result["skipped"] == 1  # 备注「体育课外测试」无格子对应，跳过 1 次

    asyncio.run(scenario())


def test_parse_image_intersection_filters_single_run_entries(monkeypatch):
    monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(config, "LLM_VISION_MODEL", "Qwen/Qwen3-VL-32B-Instruct")

    async def scenario():
        fabricated = {
            "name": "体育课外测试",
            "day_of_week": 1,
            "start_time": "19:00",
            "end_time": "20:40",
            "location": "",
            "weeks": [1, 2, 3],
        }
        run_a = {"grid": [GRID_COURSE, fabricated], "notes": []}
        run_b = {"grid": [GRID_COURSE], "notes": []}
        monkeypatch.setattr(
            vision, "_call_vision", AsyncMock(side_effect=[json.dumps(run_a), json.dumps(run_b)])
        )
        result = await vision.parse_schedule_image(b"img", "image/jpeg")
        assert len(result["courses"]) == 1
        assert result["courses"][0]["name"] == "数学"
        assert result["skipped"] == 1  # 只在单轮出现的臆造条目被交集过滤

    asyncio.run(scenario())


def test_parse_image_missing_grid_raises(monkeypatch):
    monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(config, "LLM_VISION_MODEL", "Qwen/Qwen3-VL-32B-Instruct")

    async def scenario():
        monkeypatch.setattr(vision, "_call_vision", AsyncMock(return_value='{"notes": []}'))
        with pytest.raises(vision.VisionError):
            await vision.parse_schedule_image(b"img", "image/jpeg")

    asyncio.run(scenario())


def test_parse_image_single_run_failure_falls_back(monkeypatch):
    monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(config, "LLM_VISION_MODEL", "Qwen/Qwen3-VL-32B-Instruct")

    async def scenario():
        payload = {"grid": [GRID_COURSE], "notes": []}
        monkeypatch.setattr(
            vision,
            "_call_vision",
            AsyncMock(side_effect=[vision.VisionError("上游返回 HTTP 500"), json.dumps(payload)]),
        )
        result = await vision.parse_schedule_image(b"img", "image/jpeg")
        # 一路失败 → 降级为单路结果，课程保留
        assert len(result["courses"]) == 1
        assert result["courses"][0]["name"] == "数学"
        assert result["skipped"] == 0

    asyncio.run(scenario())


def test_parse_image_both_runs_fail_raises(monkeypatch):
    monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(config, "LLM_VISION_MODEL", "Qwen/Qwen3-VL-32B-Instruct")

    async def scenario():
        monkeypatch.setattr(
            vision,
            "_call_vision",
            AsyncMock(side_effect=[vision.VisionTimeout("视觉模型响应超时")] * 2),
        )
        with pytest.raises(vision.VisionTimeout):
            await vision.parse_schedule_image(b"img", "image/jpeg")

    asyncio.run(scenario())


def test_parse_image_mime_fallback(monkeypatch):
    monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(config, "LLM_VISION_MODEL", "Qwen/Qwen3-VL-32B-Instruct")
    mocked = AsyncMock(return_value=json.dumps({"grid": [GRID_COURSE], "notes": []}))

    async def scenario():
        monkeypatch.setattr(vision, "_call_vision", mocked)
        await vision.parse_schedule_image(b"img", "")
        assert mocked.await_args.args[1] == "image/jpeg"

    asyncio.run(scenario())


def test_parse_image_timeout_propagates(monkeypatch):
    monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(config, "LLM_VISION_MODEL", "Qwen/Qwen3-VL-32B-Instruct")
    mocked = AsyncMock(side_effect=vision.VisionTimeout("视觉模型响应超时"))

    async def scenario():
        monkeypatch.setattr(vision, "_call_vision", mocked)
        with pytest.raises(vision.VisionTimeout):
            await vision.parse_schedule_image(b"img", "image/jpeg")

    asyncio.run(scenario())
