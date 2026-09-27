from src.ui.app_window import AppWindow


class _Label:
    def __init__(self):
        self.text = ""

    def configure(self, **kwargs):
        self.text = kwargs.get("text", self.text)


def test_close_when_idle_destroys_window():
    app = object.__new__(AppWindow)
    app._busy = False
    app._closing = False
    app._hide_preview = lambda: None
    app.destroyed = False
    app.destroy = lambda: setattr(app, "destroyed", True)

    app._on_close_request()

    assert app.destroyed is True


def test_close_when_busy_sets_cancel_after_confirmation(monkeypatch):
    app = object.__new__(AppWindow)
    app._busy = True
    app._closing = False
    app.cancel_flag = {"cancel": False}
    app.progress_label = _Label()
    app.destroyed = False
    app.destroy = lambda: setattr(app, "destroyed", True)
    monkeypatch.setattr("src.ui.app_window.messagebox.askyesno", lambda *_args, **_kwargs: True)

    app._on_close_request()

    assert app.cancel_flag["cancel"] is True
    assert app._closing is True
    assert app.destroyed is False
    assert "正在取消" in app.progress_label.text


def test_close_when_busy_can_be_rejected(monkeypatch):
    app = object.__new__(AppWindow)
    app._busy = True
    app._closing = False
    app.cancel_flag = {"cancel": False}
    app.progress_label = _Label()
    app.destroyed = False
    app.destroy = lambda: setattr(app, "destroyed", True)
    monkeypatch.setattr("src.ui.app_window.messagebox.askyesno", lambda *_args, **_kwargs: False)

    app._on_close_request()

    assert app.cancel_flag["cancel"] is False
    assert app._closing is False
    assert app.destroyed is False
