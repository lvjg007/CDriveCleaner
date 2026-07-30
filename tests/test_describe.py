from src.utils.describe import describe_path


def test_describe_exe():
    text = describe_path(r"C:\Users\demo\Downloads\setup.exe", category="安装包残留")
    assert "安装包" in text or "可执行" in text
    assert "setup.exe" in text


def test_describe_temp_hint():
    text = describe_path(r"C:\Users\demo\AppData\Local\Temp\abc", category="系统临时文件")
    assert "临时" in text
