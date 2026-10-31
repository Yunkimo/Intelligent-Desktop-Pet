"""生活习惯窗口测试：列表渲染、添加、删除与清空。"""

from pet.habit_dialog import HabitDialog
from pet.habits import HabitStore


def _dialog(tmp_path, **kwargs) -> tuple[HabitDialog, HabitStore]:
    store = HabitStore(tmp_path / "habits.json", **kwargs)
    return HabitDialog(store), store


def test_empty_store_disables_actions(tmp_path, qapp):
    dialog, _ = _dialog(tmp_path)

    assert dialog._list.count() == 0
    assert dialog._delete_button.isEnabled() is False
    assert dialog._clear_button.isEnabled() is False


def test_add_from_input(tmp_path, qapp):
    dialog, store = _dialog(tmp_path)

    dialog._input.setText("每天 8 点起床")
    dialog._add_habit()

    assert store.list_habits()[0]["text"] == "每天 8 点起床"
    assert dialog._list.count() == 1
    assert dialog._input.text() == ""
    assert "已记住" in dialog._status.text()


def test_add_rejects_duplicate(tmp_path, qapp):
    dialog, store = _dialog(tmp_path)
    store.add("每天 8 点起床")

    dialog._input.setText("每天8点起床")
    dialog._add_habit()

    assert "没记成" in dialog._status.text()
    assert dialog._list.count() == 1


def test_delete_selected(tmp_path, qapp):
    dialog, store = _dialog(tmp_path)
    store.add("一")
    store.add("二")
    dialog._refresh()

    dialog._list.setCurrentRow(0)
    dialog._delete_selected()

    assert [item["text"] for item in store.list_habits()] == ["二"]
    assert dialog._list.count() == 1


def test_clear_all(tmp_path, qapp):
    dialog, store = _dialog(tmp_path)
    store.add("一")
    store.add("二")
    dialog._refresh()

    dialog._clear_all()

    assert store.list_habits() == []
    assert "已清空 2 条" in dialog._status.text()
