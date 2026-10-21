"""B2 挑刺修复：pid 探活——启动清扫只清属主已死的行。"""
import os
import subprocess
import sys

from app.common.process import pid_alive


def test_pid_alive_basic():
    assert pid_alive(os.getpid()) is True      # 当前进程活着
    assert pid_alive(None) is False            # 历史遗留行（无属主）
    assert pid_alive(0) is False
    assert pid_alive(-1) is False


def test_pid_alive_real_process_lifecycle():
    """真起一个子进程：活着判活，杀掉并 wait 后判死——清扫依赖的就是这个语义"""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert pid_alive(p.pid) is True
    finally:
        p.kill()
        p.wait(timeout=10)
    assert pid_alive(p.pid) is False
