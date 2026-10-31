"""生活习惯记忆测试：增删、判重、上限、持久化与提示词注入。"""

import json

from pet.habits import MAX_TEXT_LENGTH, HabitStore
from pet.persona import build_system_prompt
from pet.tools import build_tools


class _FakeBackend:
    def list_courses(self):
        return []

    def list_tasks(self):
        return []


def _store(tmp_path, max_items=50) -> HabitStore:
    return HabitStore(tmp_path / "habits.json", max_items)


# ---------- 存储 ----------
def test_add_and_list(tmp_path):
    store = _store(tmp_path)
    ok, text = store.add("每天 8 点起床")

    assert ok is True and text == "每天 8 点起床"
    items = store.list_habits()
    assert len(items) == 1
    assert items[0]["text"] == "每天 8 点起床"
    assert items[0]["created_at"]


def test_duplicate_is_rejected_ignoring_spaces_and_case(tmp_path):
    store = _store(tmp_path)
    store.add("每天喝 八杯水")

    ok, message = store.add("每天喝八杯水")

    assert ok is False and "记过" in message
    assert len(store.list_habits()) == 1


def test_empty_and_too_long_are_rejected(tmp_path):
    store = _store(tmp_path)

    assert store.add("   ")[0] is False
    assert store.add("字" * (MAX_TEXT_LENGTH + 1))[0] is False
    assert store.list_habits() == []


def test_max_items_is_enforced(tmp_path):
    store = _store(tmp_path, max_items=2)
    store.add("一")
    store.add("二")

    ok, message = store.add("三")

    assert ok is False and "最多" in message
    assert len(store.list_habits()) == 2


def test_remove_by_id(tmp_path):
    store = _store(tmp_path)
    store.add("早点睡")
    habit_id = store.list_habits()[0]["id"]

    assert store.remove(habit_id) is True
    assert store.list_habits() == []
    assert store.remove(habit_id) is False


def test_forget_by_keyword(tmp_path):
    store = _store(tmp_path)
    store.add("每天喝咖啡")
    store.add("晚上不喝咖啡")
    store.add("每周跑步三次")

    assert store.forget("咖啡") == 2
    assert [item["text"] for item in store.list_habits()] == ["每周跑步三次"]
    assert store.forget("不存在") == 0


def test_clear_all(tmp_path):
    store = _store(tmp_path)
    store.add("一")
    store.add("二")

    assert store.clear() == 2
    assert store.clear() == 0


# ---------- 持久化 ----------
def test_persists_across_instances(tmp_path):
    path = tmp_path / "habits.json"
    first = HabitStore(path)
    first.add("每天 7 点起床")

    second = HabitStore(path)

    assert [item["text"] for item in second.list_habits()] == ["每天 7 点起床"]
    assert second.list_habits()[0]["id"] == 1


def test_next_id_continues_after_reload(tmp_path):
    path = tmp_path / "habits.json"
    first = HabitStore(path)
    first.add("一")
    first.add("二")
    first.remove(first.list_habits()[0]["id"])

    second = HabitStore(path)
    second.add("三")

    assert [item["id"] for item in second.list_habits()] == [2, 3]


def test_corrupt_file_recovers(tmp_path):
    path = tmp_path / "habits.json"
    path.write_text("{ not json", encoding="utf-8")

    store = HabitStore(path)

    assert store.load_error is not None
    assert store.list_habits() == []
    store.add("仍然能写")
    assert HabitStore(path).list_habits()[0]["text"] == "仍然能写"


def test_file_contains_plaintext_habits(tmp_path):
    path = tmp_path / "habits.json"
    _store(tmp_path).add("每天 8 点起床")

    raw = json.loads(path.read_text(encoding="utf-8"))

    assert raw["habits"][0]["text"] == "每天 8 点起床"


# ---------- 提示词与工具 ----------
def test_summary_lists_habits(tmp_path):
    store = _store(tmp_path)
    store.add("每天 8 点起床")

    summary = store.summary()

    assert "生活习惯" in summary
    assert "- 每天 8 点起床" in summary


def test_summary_empty_when_no_habits(tmp_path):
    assert _store(tmp_path).summary() == ""


def test_system_prompt_includes_habits(tmp_path):
    from pet.config import Settings

    store = _store(tmp_path)
    store.add("每天 8 点起床")

    prompt = build_system_prompt(Settings(), store.summary())

    assert "每天 8 点起床" in prompt
    assert "remember_habit" in prompt


def test_system_prompt_without_habits_has_no_summary():
    from pet.config import Settings

    prompt = build_system_prompt(Settings(), "")

    assert "生活习惯" not in prompt


def test_remember_and_forget_tools(tmp_path):
    store = _store(tmp_path)
    tools = build_tools(_FakeBackend(), store)

    assert "remember_habit" in tools and "forget_habit" in tools
    assert tools["remember_habit"].fn(text="每天 8 点起床") == "已记住：每天 8 点起床"
    assert "忘掉" in tools["forget_habit"].fn(keyword="起床")
    assert store.list_habits() == []


def test_tools_without_store_keep_original_eight():
    tools = build_tools(_FakeBackend())

    assert len(tools) == 8
    assert "remember_habit" not in tools
