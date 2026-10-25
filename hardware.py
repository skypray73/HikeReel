"""檢測 CPU / 顯示卡型號，以及 3D 渲染與影片編碼是否用到顯示卡。"""
import os
import platform
import subprocess

_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def disable_power_throttling(handle=None):
    """關閉 Windows 的「電源節流」（EcoQoS）。程式視窗不在前景時，Windows 會把它當成背景工作，
    改用省電的效率核心並降頻，影片製作可能慢好幾倍。handle 省略則是目前的行程。"""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class State(ctypes.Structure):
            _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]

        st = State(1, 0x1, 0x0)                       # 由程式自己控制「執行速度」節流，並設為關閉
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        h = wintypes.HANDLE(-1 if handle is None else int(handle))
        return bool(k32.SetProcessInformation(h, 4, ctypes.byref(st), ctypes.sizeof(st)))   # 4 = ProcessPowerThrottling
    except Exception:
        return False


def _run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=_NOWIN)
        return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""
    except Exception:
        return ""


def cpu_name():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            return str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
    except Exception:
        return platform.processor() or "未知"


def gpu_names():
    """系統裡所有顯示卡（含內顯）。"""
    out = _run(["powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"])
    return [l.strip() for l in out.splitlines() if l.strip()]


def nvidia_info():
    """NVIDIA 顯示卡：名稱、驅動版本、顯示記憶體（沒有 NVIDIA 驅動則回傳空清單）。"""
    out = _run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"])
    return [[x.strip() for x in l.split(",")] for l in out.splitlines() if l.strip()]


def opengl_renderer():
    """3D 模式實際使用的顯示晶片（VTK / OpenGL 回報），可看出是不是跑在獨立顯示卡上。"""
    try:
        import pyvista as pv
        info = pv.GPUInfo()
        return info.renderer.strip(), info.version.strip()
    except Exception as ex:
        return f"無法建立 OpenGL（{ex}）", ""


def is_discrete(name):
    n = name.lower()
    return any(k in n for k in ("nvidia", "geforce", "rtx", "quadro", "radeon rx", "radeon pro", "arc a", "arc b"))


def detect(log=print):
    """逐項檢測並回傳 (報告文字, 結果 dict)。log 會收到每一行，方便 GUI 即時顯示。"""
    import gpx_to_video as g
    lines = []

    def say(s=""):
        lines.append(s)
        log(s)

    cpu = cpu_name()
    say(f"CPU：{cpu}（{os.cpu_count()} 執行緒）")
    gpus = gpu_names()
    for n in gpus or ["（讀不到顯示卡清單）"]:
        say(f"顯示卡：{n}")
    for name, drv, mem in nvidia_info():
        say(f"NVIDIA 驅動：{name}，驅動 {drv}，顯示記憶體 {mem}")
    renderer, ver = opengl_renderer()
    gpu3d = is_discrete(renderer)
    say(f"3D 渲染晶片（OpenGL）：{renderer}" + (f"，{ver.split()[0]}" if ver else ""))
    ff = g.find_ffmpeg()
    enc, hw = g.detect_encoder()
    nvenc = enc == "h264_nvenc"
    say(f"影片編碼：{'NVIDIA NVENC（顯示卡硬體編碼）' if nvenc else ('libx264（CPU 軟體編碼）' if ff else '找不到 ffmpeg')}")
    say("")
    say("✅ 3D 畫面由獨立顯示卡渲染" if gpu3d else
        "⚠️  3D 畫面沒有跑在獨立顯示卡上。筆電請到 Windows「設定 → 系統 → 顯示器 → 圖形」"
        "把 HikeReel.exe 設為「高效能」。")
    say("✅ 影片編碼使用顯示卡（NVENC）" if nvenc else
        "ℹ️  影片編碼使用 CPU。NVIDIA 顯示卡請更新驅動程式；其他顯示卡會以 CPU 編碼。")
    say(f"ℹ️  儀表板、地標等疊圖由 CPU 處理，分散到 {max(1, min(8, (os.cpu_count() or 2) // 2))} 個行程，"
        "與顯示卡渲染同時進行；製作時切到其他視窗也會全速執行（已關閉 Windows 背景降速）。")
    return "\n".join(lines), dict(cpu=cpu, gpus=gpus, renderer=renderer, gpu3d=gpu3d, encoder=enc, nvenc=nvenc)


if __name__ == "__main__":
    detect()
