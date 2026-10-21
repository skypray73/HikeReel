# -*- coding: utf-8 -*-
"""
HikeReel — 下載 ffmpeg（選用）  —  MIT License

HikeReel 不內建 ffmpeg。第一次啟動若找不到 ffmpeg，使用者可選擇讓程式把 ffmpeg.exe 下載到 HikeReel 資料夾。

來源與授權（會在介面上顯示）：
  * 下載來源：gyan.dev 的 FFmpeg Windows 建置「release essentials」
    https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
  * 校驗：下載後用同站提供的 SHA-256 檔驗證，不符就不安裝。
  * 授權：該建置為 GPL v3（靜態編譯）。FFmpeg 是 FFmpeg 專案的獨立軟體，不是 HikeReel 的一部分，
    HikeReel 只把它當成外部程式呼叫，沒有修改它。原始碼：https://ffmpeg.org/ 、https://www.gyan.dev/ffmpeg/builds/
  * 安裝內容：ffmpeg.exe，以及該壓縮檔附的授權文件（存成 ffmpeg_LICENSE.txt），和一份來源說明 ffmpeg_SOURCE.txt。
"""
import hashlib
import io
import os
import sys
import tempfile
import time
import urllib.request
import zipfile

try:                                        # 使用 Windows 系統憑證庫（公司/學校網路的 SSL 檢查）
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

BASE = "https://www.gyan.dev/ffmpeg/builds/"
ZIP_NAME = "ffmpeg-release-essentials.zip"
ZIP_URL = BASE + ZIP_NAME
SHA_URL = ZIP_URL + ".sha256"
VERSION_URL = BASE + "release-version"
HOMEPAGE = "https://www.gyan.dev/ffmpeg/builds/"
FFMPEG_ORG = "https://ffmpeg.org/"
LICENSE_NAME = "GPL v3"
UA = "HikeReel/2.0 (+https://github.com/skypray73/HikeReel)"


def app_dir():
    return os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))


def local_dir():
    """程式資料夾不能寫入時的備用位置。"""
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "HikeReel", "ffmpeg")


def _writable(d):
    try:
        os.makedirs(d, exist_ok=True)
        t = os.path.join(d, ".write_test")
        with open(t, "w"):
            pass
        os.remove(t)
        return True
    except OSError:
        return False


def target_dir():
    """安裝位置：優先 HikeReel 資料夾（和 HikeReel.exe 放一起）；不能寫入就用 %LOCALAPPDATA%\\HikeReel\\ffmpeg。"""
    return app_dir() if _writable(app_dir()) else local_dir()


def _get(url, timeout=60):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout)


def remote_info():
    """回傳 (版本, 檔案大小 bytes)；連不上回傳 (None, None)。"""
    try:
        ver = _get(VERSION_URL, 20).read().decode("utf-8", "replace").strip()
    except Exception:
        ver = None
    try:
        size = int(urllib.request.urlopen(urllib.request.Request(ZIP_URL, method="HEAD", headers={"User-Agent": UA}),
                                          timeout=20).headers.get("Content-Length") or 0) or None
    except Exception:
        size = None
    return ver, size


def download_ffmpeg(progress=None, dest=None):
    """下載 → 驗證 SHA-256 → 只解出 ffmpeg.exe 與授權文件。回傳 ffmpeg.exe 路徑；失敗丟出 RuntimeError（訊息可直接顯示給使用者）。
    progress(階段文字, 0~1 或 None) 會被呼叫以更新介面。"""
    dest = dest or target_dir()
    os.makedirs(dest, exist_ok=True)
    say = progress or (lambda *_: None)

    say("取得校驗碼…", None)
    try:
        want = _get(SHA_URL, 30).read().decode("ascii", "replace").split()[0].strip().lower()
        if len(want) != 64:
            raise ValueError("格式不對")
    except Exception as e:
        raise RuntimeError(f"無法取得校驗碼（{e}）。請確認網路連線，或改用 winget / 手動安裝。")

    fd, tmp = tempfile.mkstemp(prefix="ffmpeg_", suffix=".zip")
    os.close(fd)
    try:
        h = hashlib.sha256()
        try:
            r = _get(ZIP_URL, 60)
            total = int(r.headers.get("Content-Length") or 0)
            got, t0 = 0, time.time()
            with open(tmp, "wb") as f:
                while True:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    mb = got / 1048576
                    say(f"下載中… {mb:.0f}" + (f" / {total / 1048576:.0f}" if total else "") + " MB",
                        (got / total) if total else None)
        except Exception as e:
            raise RuntimeError(f"下載失敗（{e}）。請確認網路連線後再試。")

        say("驗證檔案…", None)
        if h.hexdigest().lower() != want:
            raise RuntimeError("檔案校驗碼不符（SHA-256），可能下載不完整或被竄改，已放棄安裝。請再試一次。")

        say("解壓縮…", None)
        try:
            with zipfile.ZipFile(tmp) as z:
                names = z.namelist()
                exe = next((n for n in names if n.lower().endswith("/bin/ffmpeg.exe") or n.lower() == "bin/ffmpeg.exe"), None)
                if not exe:
                    raise RuntimeError("壓縮檔裡找不到 ffmpeg.exe")
                lic = next((n for n in names if n.lower().endswith("/license") or n.lower() == "license"), None)
                out_exe = os.path.join(dest, "ffmpeg.exe")
                with z.open(exe) as src, open(out_exe + ".part", "wb") as dst:
                    while True:
                        b = src.read(1024 * 1024)
                        if not b:
                            break
                        dst.write(b)
                os.replace(out_exe + ".part", out_exe)
                if lic:
                    with z.open(lic) as src, open(os.path.join(dest, "ffmpeg_LICENSE.txt"), "wb") as dst:
                        dst.write(src.read())
                ver = exe.split("/")[0]
        except zipfile.BadZipFile:
            raise RuntimeError("下載的檔案不是有效的壓縮檔。請再試一次。")

        with open(os.path.join(dest, "ffmpeg_SOURCE.txt"), "w", encoding="utf-8") as f:
            f.write("這個資料夾裡的 ffmpeg.exe 不是 HikeReel 的一部分，是 FFmpeg 專案的獨立軟體（GPL v3 授權）。\n"
                    "HikeReel 只把它當成外部程式呼叫，沒有修改它；不想使用時直接刪除 ffmpeg.exe 即可。\n\n"
                    f"建置版本：{ver}\n"
                    f"下載來源：{ZIP_URL}\n"
                    f"校驗（SHA-256）：{want}\n"
                    f"建置提供者：{HOMEPAGE}\n"
                    f"FFmpeg 專案與原始碼：{FFMPEG_ORG}\n"
                    f"授權文件：ffmpeg_LICENSE.txt\n"
                    f"下載時間：{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        return out_exe
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def verify_works(exe):
    """執行 ffmpeg -version 確認可以用。"""
    import subprocess
    try:
        r = subprocess.run([exe, "-version"], capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0 and b"ffmpeg version" in r.stdout[:200]
    except Exception:
        return False
