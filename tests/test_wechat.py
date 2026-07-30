import hashlib

from src.scanners.wechat import classify_session, discover_chat_id_map


def test_classify_chatroom_name():
    kind, display, _ = classify_session("123456@chatroom", {})
    assert kind == "群聊"
    assert "chatroom" in display


def test_classify_mapped_friend(tmp_path):
    chat_id = "wxid_demo_user"
    md5 = hashlib.md5(chat_id.encode("utf-8")).hexdigest()
    id_map = {md5: (chat_id, "friend")}
    kind, display, _ = classify_session(md5, id_map)
    assert kind == "个人"
    assert display == chat_id


def test_classify_mapped_group():
    chat_id = "demo_group@chatroom"
    md5 = hashlib.md5(chat_id.encode("utf-8")).hexdigest()
    id_map = {md5: (chat_id, "group")}
    kind, display, _ = classify_session(md5, id_map)
    assert kind == "群聊"


def test_discover_from_config(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "ids.txt").write_text(
        "wxid_abc123\nother 999@chatroom end\n", encoding="utf-8"
    )
    mapping = discover_chat_id_map(tmp_path)
    assert any(v[0] == "wxid_abc123" for v in mapping.values())
    assert any(v[1] == "group" for v in mapping.values())
