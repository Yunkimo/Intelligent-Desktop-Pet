"""Memory 会话历史测试。"""

from pet.memory import Memory


def test_add_and_order():
    m = Memory("unused.json", max_turns=10, persist=False)
    m.set_system("你是宠物")
    m.add_user("你好")
    m.add_assistant("你好呀")
    msgs = m.get_messages()
    assert msgs[0] == {"role": "system", "content": "你是宠物"}
    assert msgs[1] == {"role": "user", "content": "你好"}
    assert msgs[2] == {"role": "assistant", "content": "你好呀"}


def test_clear_history_keeps_system():
    m = Memory("unused.json", max_turns=10, persist=False)
    m.set_system("你是宠物")
    m.add_user("你好")
    m.add_assistant("你好呀")
    m.clear_history()
    assert m.get_messages() == [{"role": "system", "content": "你是宠物"}]


def test_trim_keeps_recent_turns():
    m = Memory("unused.json", max_turns=2, persist=False)
    m.set_system("sys")
    for i in range(5):
        m.add_user(f"u{i}")
        m.add_assistant(f"a{i}")
    msgs = m.get_messages()
    assert msgs[0]["role"] == "system"
    rest = msgs[1:]
    assert len(rest) == 4  # 最近 2 轮
    assert rest[0]["content"] == "u3"
    assert rest[-1]["content"] == "a4"


def test_persist_roundtrip(tmp_path):
    path = tmp_path / "data" / "history.json"
    m = Memory(path, max_turns=10, persist=True)
    m.set_system("sys")
    m.add_user("hi")
    m.add_assistant("hello")
    m.save()

    m2 = Memory(path, persist=True)
    msgs = m2.get_messages()
    assert msgs[1]["content"] == "hi"
    assert msgs[2]["content"] == "hello"
