"""进程存活检测（B2 挑刺修复）：启动清扫只清「属主进程已死」的在途行。

单机部署约定（课程项目规模）：后端单机、库文件同机共享。两个后端进程共用
一个库时，后启动者清扫前先看行主人的 pid 是否还活着——活着就不动，从根上
杜绝"第二个进程把第一个正在跑的解析/匹配杀成失败"。
"""
import ctypes
import os


def pid_alive(pid: int | None) -> bool:
    """进程是否存活。pid=None 视为不存活（历史遗留行，清扫安全）。"""
    if pid is None or pid <= 0:
        return False
    if os.name == "nt":
        # Windows 上 os.kill(pid, 0) 会真的终止进程，必须走 OpenProcess 探测。
        # 只看 OpenProcess 成功不够：进程刚被杀、句柄未清时会仍拿得到句柄——
        # 再查退出码，非 STILL_ACTIVE 即已死（测试实测抓到过这个坑）
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 0x103
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False  # 无权限或不存在；ERROR_ACCESS_LEVEL 的情况按不存在处理（清扫误伤面仅为多账户共机，可接受）
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True  # 查不到退出码按活着处理（清扫宁漏勿杀）
            return code.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)  # POSIX：信号 0 只探活不发送
        return True
    except OSError:
        return False
