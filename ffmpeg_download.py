# -*- coding: utf-8 -*-
"""
HikeReel — 下載 ffmpeg（選用）  —  MIT License

HikeReel 不內建 ffmpeg。第一次啟動若找不到 ffmpeg，使用者可選擇讓程式把 ffmpeg.exe 下載到 HikeReel 資料夾。

來源與授權（會在介面上顯示）：
  * 下載來源（依序嘗試）：
      1) GitHub：gyan.dev 作者發佈的 FFmpeg Windows 建置 https://github.com/GyanD/codexffmpeg/releases （CDN 快，約 5～6 MB/s）
      2) 備援：gyan.dev https://www.gyan.dev/ffmpeg/builds/ （同一個檔案，但伺服器較慢）
    兩處都是「release essentials」建置，同一個 zip（SHA-256 相同）。
  * 校驗：下載後以 SHA-256 驗證——GitHub 公布的 digest，並與 gyan.dev 的 .sha256 交叉核對；不符就不安裝。
  * 授權：該建置為 GPL v3（靜態編譯）。FFmpeg 是 FFmpeg 專案的獨立軟體，不是 HikeReel 的一部分，
    HikeReel 只把它當成外部程式呼叫，沒有修改它。原始碼：https://ffmpeg.org/ 、https://github.com/FFmpeg/FFmpeg
  * 安裝內容：ffmpeg.exe，以及該壓縮檔附的授權文件（存成 ffmpeg_LICENSE.txt），和一份來源說明 ffmpeg_SOURCE.txt。
  * 網路不穩或卡住時會自動從中斷處續傳（HTTP Range）。
"""
import hashlib
import io
import json
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
ZIP_URL = BASE + ZIP_NAME                         # 備援（較慢）
SHA_URL = ZIP_URL + ".sha256"
VERSION_URL = BASE + "release-version"
HOMEPAGE = "https://www.gyan.dev/ffmpeg/builds/"
GITHUB_API = "https://api.github.com/repos/GyanD/codexffmpeg/releases/latest"
GITHUB_PAGE = "https://github.com/GyanD/codexffmpeg/releases"
FFMPEG_ORG = "https://ffmpeg.org/"
LICENSE_NAME = "GPL v3"
UA = "HikeReel/2.0 (+https://github.com/skypray73/HikeReel)"
STALL_SECONDS = 25                                # 這麼久沒收到資料就中斷重連續傳
MAX_RETRIES = 6


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


def _get_range(url, start, timeout):
    h = {"User-Agent": UA}
    if start:
        h["Range"] = f"bytes={start}-"
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout)


def github_asset():
    """從 GitHub 取得 essentials .zip 的 (下載網址, 大小, sha256, 版本)；失敗回傳 None。"""
    try:
        rel = json.loads(_get(GITHUB_API, 30).read().decode("utf-8", "replace"))
        for a in rel.get("assets", []):
            if a["name"].endswith("essentials_build.zip"):
                dg = (a.get("digest") or "").lower()
                sha = dg.split(":", 1)[1] if dg.startswith("sha256:") else None
                return a["browser_download_url"], int(a.get("size") or 0), sha, rel.get("tag_name", "")
    except Exception:
        pass
    return None


def gyan_checksum():
    """gyan.dev 公布的 zip SHA-256 與版本；失敗回傳 (None, None)。"""
    sha = ver = None
    try:
        t = _get(SHA_URL, 20).read().decode("ascii", "replace").split()[0].strip().lower()
        sha = t if len(t) == 64 else None
    except Exception:
        pass
    try:
        ver = _get(VERSION_URL, 20).read().decode("utf-8", "replace").strip()
    except Exception:
        pass
    return sha, ver


def remote_info():
    """回傳 (版本, 檔案大小 bytes)；連不上回傳 (None, None)。"""
    a = github_asset()
    if a:
        return a[3], a[1] or None
    sha, ver = gyan_checksum()
    return ver, None


def _download_resumable(url, path, total, say, label):
    """下載到 path，卡住或中斷時用 Range 從已下載的位置續傳。回傳 SHA-256（以完整檔案計算）。"""
    got = 0
    open(path, "wb").close()
    tries = 0
    t_start = time.time()
    last_t, last_got, speed = time.time(), 0, 0.0
    while True:
        try:
            r = _get_range(url, got, STALL_SECONDS)
            if got and r.status != 206:                       # 伺服器不支援續傳 → 從頭來
                got = 0
                open(path, "wb").close()
                r = _get_range(url, 0, STALL_SECONDS)
            if not total:
                total = got + int(r.headers.get("Content-Length") or 0)
            with open(path, "ab") as f:
                while True:
                    chunk = r.read(256 * 1024)                # 超過 STALL_SECONDS 沒資料 → 丟出 timeout 例外
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    now = time.time()
                    if now - last_t >= 0.5:
                        speed = (got - last_got) / (now - last_t) / 1048576
                        last_t, last_got = now, got
                    say(f"{label}… {got / 1048576:.0f} / {total / 1048576:.0f} MB（{speed:.1f} MB/s）" if total
                        else f"{label}… {got / 1048576:.0f} MB（{speed:.1f} MB/s）",
                        (got / total) if total else None)
            if total and got < total:
                raise OSError("連線提前結束")
            break
        except Exception as e:
            tries += 1
            if tries > MAX_RETRIES:
                raise RuntimeError(f"下載中斷且重試 {MAX_RETRIES} 次仍失敗（{e}）")
            say(f"連線不穩，從 {got / 1048576:.0f} MB 處續傳（第 {tries} 次）…", (got / total) if total else None)
            time.sleep(min(2 * tries, 8))
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def download_ffmpeg(progress=None, dest=None):
    """下載 → 驗證 SHA-256 → 只解出 ffmpeg.exe 與授權文件。回傳 ffmpeg.exe 路徑；失敗丟出 RuntimeError（訊息可直接顯示給使用者）。
    progress(階段文字, 0~1 或 None) 會被呼叫以更新介面。"""
    dest = dest or target_dir()
    os.makedirs(dest, exist_ok=True)
    say = progress or (lambda *_: None)

    say("取得下載資訊…", None)
    gh = github_asset()
    g_sha, g_ver = gyan_checksum()
    candidates = []                       # (標籤, 網址, 大小, 預期 SHA-256 清單, 來源說明)
    if gh:
        url, size, gh_sha, tag = gh
        expect = [x for x in (gh_sha, g_sha if (g_ver and tag and g_ver == tag) else None) if x]
        if expect:
            candidates.append(("GitHub", url, size, expect, "GitHub：GyanD/codexffmpeg"))
    if g_sha:
        candidates.append(("gyan.dev", ZIP_URL, 0, [g_sha], "gyan.dev"))
    if not candidates:
        raise RuntimeError("無法取得下載資訊與校驗碼。請確認網路連線，或改用 winget / 手動安裝。")

    fd, tmp = tempfile.mkstemp(prefix="ffmpeg_", suffix=".zip")
    os.close(fd)
    used, want, errors = None, None, []
    try:
        for label, url, size, expect, desc in candidates:
            try:
                say(f"從 {label} 下載…", None)
                got_sha = _download_resumable(url, tmp, size, say, f"從 {label} 下載")
            except RuntimeError as e:
                errors.append(f"{label}：{e}")
                continue
            say("驗證檔案…", None)
            if all(got_sha == x for x in expect):
                used, want = (label, url, desc), got_sha
                break
            errors.append(f"{label}：校驗碼不符（SHA-256）")
        if not used:
            if any("校驗碼不符" in e for e in errors):
                raise RuntimeError("檔案校驗碼不符（SHA-256），可能下載不完整或被竄改，已放棄安裝。請再試一次。")
            raise RuntimeError("下載失敗（" + "；".join(errors) + "）。請確認網路連線後再試。")

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
                    f"實際下載來源：{used[1]}（{used[2]}）\n"
                    f"校驗（SHA-256）：{want}\n"
                    f"建置提供者：gyan.dev（{HOMEPAGE}）；GitHub 發佈：{GITHUB_PAGE}\n"
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
