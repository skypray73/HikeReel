# -*- coding: utf-8 -*-
"""
HikeReel 3D 地形飛行模式（原型）  —  MIT License

把 GPX 軌跡畫在 3D 地形上，相機沿路線飛行，輸出成 Shorts / Reels 用的影片。
全部使用開放資料，執行時才從網路下載（並快取在本機）：
  * 地形高程：AWS Terrain Tiles (Terrarium)  https://registry.opendata.aws/terrain-tiles/
  * 貼圖：OpenTopoMap / OpenStreetMap，或 Sentinel-2 cloudless 衛星影像（EOX，2016 / 2024 版）
    - s2-2016：CC BY 4.0（可商用，需標示來源）
    - s2-2024：CC BY-NC-SA 4.0（僅限非商業使用；以它製作的影片須以相同條款分享、標示來源）

用法：
  python terrain3d.py track.gpx --title "玉山主峰" --texture topo --exaggeration 1.6
"""
import argparse
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

for _s in (sys.stdout, sys.stderr):          # Windows 主控台（cp950）印不出 emoji 時不要當掉
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

try:                                        # 使用 Windows 系統憑證庫（公司/學校網路常有 SSL 檢查，certifi 驗證會失敗）
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import numpy as np
from PIL import Image, ImageDraw

import gpx_to_video as g          # 沿用既有的 GPX 解析、坡度顏色、字型、ffmpeg 偵測
from landmark_photos import PhotoCard, build_schedule, default_folder, find_photo, landmark_photo_table

UA = g.HIKEREEL_UA if getattr(g, "HAS_CTX", False) else "HikeReel/1.1 (+https://github.com/skypray73/HikeReel)"
_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)       # 打包成視窗程式時，呼叫 ffmpeg 不要跳出黑色主控台
DEM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
CACHE = os.path.join(os.path.expanduser("~"), ".hikereel_tile_cache")
R_EARTH = 6378137.0


# ── 座標 ──────────────────────────────────────────────────
def merc(lon, lat):
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    return (R_EARTH * np.radians(lon),
            R_EARTH * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)))


def tile_bounds(x, y, z):
    n = 2 ** z
    size = 2 * math.pi * R_EARTH / n
    x0 = -math.pi * R_EARTH + x * size
    y1 = math.pi * R_EARTH - y * size
    return x0, y1 - size, x0 + size, y1          # xmin, ymin, xmax, ymax


def lonlat_to_tile(lon, lat, z):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


# ── 高程 ──────────────────────────────────────────────────
def fetch_tile(url, path):
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r, open(path + ".part", "wb") as f:
                f.write(r.read())
            os.replace(path + ".part", path)
            return path
        except Exception as e:                   # 網路暫時失敗就重試
            last = e
            time.sleep(1)
    raise RuntimeError(f"下載失敗：{url}（{last}）")


def fetch_dem(west, south, east, north, max_px=2048):
    """回傳 (elev[ny,nx] 公尺, (xmin, ymin, xmax, ymax) Web Mercator)。"""
    z = 8
    for zz in range(8, 16):
        x0, y0 = lonlat_to_tile(west, north, zz)
        x1, y1 = lonlat_to_tile(east, south, zz)
        if (x1 - x0 + 1) * 256 > max_px or (y1 - y0 + 1) * 256 > max_px:
            break
        z = zz
    x0, y0 = lonlat_to_tile(west, north, z)
    x1, y1 = lonlat_to_tile(east, south, z)
    nx, ny = x1 - x0 + 1, y1 - y0 + 1
    print(f"   高程：zoom {z}，{nx}×{ny} 張圖磚")
    mosaic = np.zeros((ny * 256, nx * 256), np.float32)
    for ty in range(y0, y1 + 1):
        for tx in range(x0, x1 + 1):
            p = fetch_tile(DEM_URL.format(z=z, x=tx, y=ty),
                           os.path.join(CACHE, "dem", str(z), str(tx), f"{ty}.png"))
            a = np.asarray(Image.open(p).convert("RGB"), np.float32)
            mosaic[(ty - y0) * 256:(ty - y0 + 1) * 256, (tx - x0) * 256:(tx - x0 + 1) * 256] = \
                a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
    xa = tile_bounds(x0, y0, z)
    xb = tile_bounds(x1, y1, z)
    return mosaic, (xa[0], xb[1], xb[2], xa[3])


# ── 貼圖 ──────────────────────────────────────────────────
TERRAIN_CREDIT = "Terrain: Mapzen / AWS Terrain Tiles"
EOX_URL = "https://tiles.maps.eox.at/wmts/1.0.0/{layer}/default/g/{{z}}/{{y}}/{{x}}.jpg"
TEXTURES = {
    "topo": dict(label="OpenTopoMap 地形圖", max_zoom=17, license="CC BY-SA",
                 credit=["© OpenStreetMap contributors, SRTM | Map style © OpenTopoMap (CC BY-SA)"]),
    "osm": dict(label="OpenStreetMap", max_zoom=19, license="ODbL",
                credit=["© OpenStreetMap contributors"]),
    "s2-2016": dict(label="衛星影像 Sentinel-2 cloudless 2016", max_zoom=15, layer="s2cloudless_3857",
                    license="CC BY 4.0",
                    credit=["Sentinel-2 cloudless - https://s2maps.eu by EOX IT Services GmbH",
                            "(Contains modified Copernicus Sentinel data 2016 & 2017) · CC BY 4.0"]),
    "s2-2024": dict(label="衛星影像 Sentinel-2 cloudless 2024", max_zoom=15, layer="s2cloudless-2024_3857",
                    license="CC BY-NC-SA 4.0",
                    notice="⚠️  Sentinel-2 cloudless 2024 為 CC BY-NC-SA 4.0：僅限非商業使用（含開啟營利的影片），"
                           "以它製作的影片須以相同條款分享並標示來源。可商用請改用 s2-2016。",
                    credit=["Sentinel-2 cloudless - https://s2maps.eu by EOX IT Services GmbH",
                            "(Contains modified Copernicus Sentinel data 2024) · CC BY-NC-SA 4.0 非商業"]),
}


ESRI_URL = "https://ibasemaps-api.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
TEXTURES["esri"] = dict(
    label="衛星影像 Esri World Imagery（需自備 ArcGIS 金鑰）", max_zoom=18, license="Esri 使用條款",
    notice="⚠️  Esri World Imagery：須使用你自己的 ArcGIS Location Platform 金鑰（環境變數 ARCGIS_API_KEY），"
           "圖磚不會存到硬碟。影片公開分享須保留畫面上的來源標示；開啟營利或商業用途請先確認 Esri 條款。",
    credit=["Powered by Esri · Imagery: Esri, Vantor, GeoEye, Earthstar Geographics,",
            "CNES/Airbus DS, USDA, USGS, AeroGRID, IGN, and the GIS User Community"])


def arcgis_key():
    """讀取 ArcGIS 金鑰：先看環境變數，無效時（例如還沒重開終端機）改讀 Windows 使用者環境變數。不會印出金鑰。"""
    k = os.environ.get("ARCGIS_API_KEY", "").strip()
    if k and k.isascii() and len(k) >= 20:
        return k
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as h:
            k = str(winreg.QueryValueEx(h, "ARCGIS_API_KEY")[0]).strip()
            if k.isascii() and len(k) >= 20:
                return k
    except Exception:
        pass
    return None


ESRI_CACHE_SECONDS = 86400       # 依伺服器回傳的 Cache-Control: max-age=86400，最多暫存 24 小時


def purge_esri_cache(root):
    """刪除超過 24 小時的 Esri 暫存圖磚（Esri 不允許把圖磚當成離線資料長期保存）。"""
    now = time.time()
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            fp = os.path.join(dirpath, f)
            try:
                if now - os.path.getmtime(fp) > ESRI_CACHE_SECONDS:
                    os.remove(fp)
            except OSError:
                pass


def save_arcgis_key(key):
    """把金鑰存到 Windows 使用者環境變數 ARCGIS_API_KEY（只存在這台電腦，不會上傳），並立即對本程式生效。"""
    key = key.strip()
    os.environ["ARCGIS_API_KEY"] = key
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as h:
            winreg.SetValueEx(h, "ARCGIS_API_KEY", 0, winreg.REG_SZ, key)
        import ctypes                                   # 通知其他程式環境變數已更新
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 2000, None)
    except Exception:
        pass


def check_arcgis_key(key):
    """實際下載一張圖磚確認金鑰可用。回傳 (是否可用, 說明)。"""
    url = ESRI_URL.format(z=1, x=0, y=0) + "?token=" + key.strip()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20) as r:
            ok = r.status == 200 and r.headers.get("Content-Type", "").startswith("image")
            return ok, "金鑰可用" if ok else "伺服器回應異常"
    except urllib.error.HTTPError as e:
        return False, f"金鑰無效或權限不足（HTTP {e.code}）。建立金鑰時請開啟「底圖 → 靜態底圖圖磚」權限。"
    except Exception as e:
        return False, f"無法連線到 Esri（{e}）"


def fetch_esri(xmin, ymin, xmax, ymax, max_tiles):
    """Esri World Imagery：圖磚依 HTTP 標頭最多暫存 24 小時，同一天重做不必重新下載，過期自動刪除。"""
    from concurrent.futures import ThreadPoolExecutor
    import io
    key = arcgis_key()
    if not key:
        raise RuntimeError("找不到 ArcGIS 金鑰。請在 HikeReel 選 3D 時輸入，或在 PowerShell 執行：setx ARCGIS_API_KEY \"你的金鑰\"")
    from pyproj import Transformer
    to_ll = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    w, s_ = to_ll.transform(xmin, ymin)
    e, n = to_ll.transform(xmax, ymax)
    z = 10
    for zz in range(10, TEXTURES["esri"]["max_zoom"] + 1):
        x0, y0 = lonlat_to_tile(w, n, zz)
        x1, y1 = lonlat_to_tile(e, s_, zz)
        if (x1 - x0 + 1) * (y1 - y0 + 1) > max_tiles:
            break
        z = zz
    x0, y0 = lonlat_to_tile(w, n, z)
    x1, y1 = lonlat_to_tile(e, s_, z)
    nx, ny = x1 - x0 + 1, y1 - y0 + 1
    cache_root = os.path.join(CACHE, "esri_24h")
    purge_esri_cache(cache_root)
    stats = {"hit": 0, "dl": 0}

    def get(xy):
        tx, ty = xy
        cp = os.path.join(cache_root, str(z), str(tx), f"{ty}.jpg")       # 檔名不含金鑰
        try:
            if time.time() - os.path.getmtime(cp) < ESRI_CACHE_SECONDS:
                stats["hit"] += 1
                return xy, np.asarray(Image.open(cp).convert("RGB"))
        except (OSError, ValueError):
            pass
        url = ESRI_URL.format(z=z, x=tx, y=ty) + "?token=" + key
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    raw = r.read()
                a = np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"))
                try:
                    os.makedirs(os.path.dirname(cp), exist_ok=True)
                    with open(cp, "wb") as f:
                        f.write(raw)
                except OSError:
                    pass
                stats["dl"] += 1
                return xy, a
            except urllib.error.HTTPError as ex:
                if ex.code in (401, 403):
                    raise RuntimeError(f"ArcGIS 金鑰無效或權限不足（HTTP {ex.code}）") from None
                time.sleep(1 + attempt)
            except Exception:
                time.sleep(1 + attempt)
        return xy, None

    tiles = [(tx, ty) for ty in range(y0, y1 + 1) for tx in range(x0, x1 + 1)]
    with ThreadPoolExecutor(max_workers=8) as ex:
        got = dict(ex.map(get, tiles))
    ts = next((a.shape[0] for a in got.values() if a is not None), 256)
    img = np.zeros((ny * ts, nx * ts, 3), np.uint8)
    for (tx, ty), a in got.items():
        if a is not None:
            img[(ty - y0) * ts:(ty - y0 + 1) * ts, (tx - x0) * ts:(tx - x0 + 1) * ts] = a[:ts, :ts]
    print(f"   Esri 圖磚：下載 {stats['dl']} 張，使用 24 小時內暫存 {stats['hit']} 張")
    missing = sum(a is None for a in got.values())
    if missing:
        print(f"   ⚠️  {missing} 張圖磚下載失敗")
    a = tile_bounds(x0, y0, z)
    b = tile_bounds(x1, y1, z)
    return img, (a[0], b[2], b[1], a[3])              # (xmin, xmax, ymin, ymax)


def texture_provider(source):
    import contextily as ctx
    t = TEXTURES[source]
    if source == "topo":
        return ctx.providers.OpenTopoMap
    if source == "osm":
        return ctx.providers.OpenStreetMap.Mapnik
    import xyzservices
    return xyzservices.TileProvider(name=source, url=EOX_URL.format(layer=t["layer"]),
                                    attribution=" ".join(t["credit"]), max_zoom=t["max_zoom"])


def fetch_texture(xmin, ymin, xmax, ymax, source="topo", max_tiles=None):
    if source == "esri":
        return fetch_esri(xmin, ymin, xmax, ymax, max_tiles=max_tiles or 1200)    # 高解析：最多約 1200 張（免費額度每月 200 萬張）
    max_tiles = max_tiles or 100
    import contextily as ctx
    prov = texture_provider(source)
    from pyproj import Transformer
    to_ll = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    w, s = to_ll.transform(xmin, ymin)
    e, n = to_ll.transform(xmax, ymax)
    z = 10
    for zz in range(10, TEXTURES[source]["max_zoom"] + 1):
        x0, y0 = lonlat_to_tile(w, n, zz)
        x1, y1 = lonlat_to_tile(e, s, zz)
        if (x1 - x0 + 1) * (y1 - y0 + 1) > max_tiles:
            break
        z = zz
    print(f"   貼圖：{source}，zoom {z}")
    img, ext = ctx.bounds2img(xmin, ymin, xmax, ymax, zoom=z, source=prov,
                              headers={"User-Agent": UA})
    return img[..., :3], ext                     # ext = (xmin, xmax, ymin, ymax)


# ── 場景資料 ──────────────────────────────────────────────
def crop_dem(dem, dext, text):
    """把高程裁到貼圖也涵蓋的範圍；回傳 (dem, 每欄 Mercator x, 每列 y)。"""
    ix0, ix1 = max(dext[0], text[0]), min(dext[2], text[1])
    iy0, iy1 = max(dext[1], text[2]), min(dext[3], text[3])
    px, py = (dext[2] - dext[0]) / dem.shape[1], (dext[3] - dext[1]) / dem.shape[0]
    c0, c1 = int(math.ceil((ix0 - dext[0]) / px)), int((ix1 - dext[0]) / px)
    r0, r1 = int(math.ceil((dext[3] - iy1) / py)), int((dext[3] - iy0) / py)
    mx = dext[0] + (np.arange(c0, c1) + 0.5) * px
    my = dext[3] - (np.arange(r0, r1) + 0.5) * py
    return dem[r0:r1, c0:c1], mx, my


class Scene:
    def __init__(self, data, texture="topo", exaggeration=1.5):
        lats, lons = data["lats"], data["lons"]
        padx, pady = (lons.max() - lons.min()) * 0.6 + 0.006, (lats.max() - lats.min()) * 0.6 + 0.006
        w, e = lons.min() - padx, lons.max() + padx
        s, n = lats.min() - pady, lats.max() + pady
        print("\n🌐 下載地形高程...")
        dem, dext = fetch_dem(w, s, e, n)
        print("🌐 下載貼圖...")
        (mw, ms), (me, mn) = merc(w, s), merc(e, n)
        xm, ym = max(dext[0], float(mw)), max(dext[1], float(ms))
        xM, yM = min(dext[2], float(me)), min(dext[3], float(mn))
        tex, text = fetch_texture(xm, ym, xM, yM, texture)

        self.dem, self.mx, self.my = crop_dem(dem, dext, text)        # 只保留貼圖與高程都涵蓋的範圍
        self.tex, self.text = tex, text
        self.texture, self.bbox = texture, (w, s, e, n)

        lat0 = float(lats.mean())
        self.k = math.cos(math.radians(lat0))                        # Mercator 公尺 → 實際公尺
        self.cx, self.cy = merc(lons.mean(), lat0)[0], merc(lons.mean(), lat0)[1]
        self.ex = float(exaggeration)

        # 軌跡 → 場景座標，高度貼著地形
        tx, ty = merc(lons, lats)
        self.tx, self.ty = (tx - self.cx) * self.k, (ty - self.cy) * self.k
        tz = self.sample(tx, ty)
        self.tz = tz * self.ex
        self.data = data

    def sample(self, mx, my):
        """用雙線性內插取得地形高度（公尺，未乘誇張倍率）。"""
        fx = (np.asarray(mx) - self.mx[0]) / (self.mx[1] - self.mx[0])
        fy = (np.asarray(my) - self.my[0]) / (self.my[1] - self.my[0])
        fx = np.clip(fx, 0, len(self.mx) - 1.001)
        fy = np.clip(fy, 0, len(self.my) - 1.001)
        x0, y0 = fx.astype(int), fy.astype(int)
        ax, ay = fx - x0, fy - y0
        d = self.dem
        return (d[y0, x0] * (1 - ax) * (1 - ay) + d[y0, x0 + 1] * ax * (1 - ay)
                + d[y0 + 1, x0] * (1 - ax) * ay + d[y0 + 1, x0 + 1] * ax * ay)

    def terrain_at(self, X, Y):
        """場景座標 → 地形高度（含誇張倍率）。"""
        return self.sample(X / self.k + self.cx, Y / self.k + self.cy) * self.ex

    def build_mesh(self, pv):
        return self._mesh(pv, self.dem, self.mx, self.my, self.tex, self.text)

    def build_outer(self, pv, scale=4.0):
        """外圍地形：範圍約為主地形的 4 倍、解析度較低，讓地形延伸到地平線，不會像一座孤島。
        主地形範圍內的外圍網格往下壓，避免低解析地形從主地形穿出來。"""
        w, s_, e, n = self.bbox
        cxd, cyd = (w + e) / 2, (s_ + n) / 2
        hw, hh = (e - w) / 2 * scale, (n - s_) / 2 * scale
        W2, E2 = cxd - hw, cxd + hw
        S2, N2 = max(-84.0, cyd - hh), min(84.0, cyd + hh)
        print("🌐 下載外圍地形（較低解析）...")
        dem, dext = fetch_dem(W2, S2, E2, N2, max_px=1024)
        (mw, ms), (me, mn) = merc(W2, S2), merc(E2, N2)
        xm, ym = max(dext[0], float(mw)), max(dext[1], float(ms))
        xM, yM = min(dext[2], float(me)), min(dext[3], float(mn))
        tex, text = fetch_texture(xm, ym, xM, yM, self.texture,
                                  max_tiles=300 if self.texture == "esri" else 120)
        dem, mx, my = crop_dem(dem, dext, text)
        # 主地形範圍（縮一格）內的點往下壓
        cell = abs(mx[1] - mx[0])
        inx = (mx > self.mx.min() + cell) & (mx < self.mx.max() - cell)
        iny = (my > self.my.min() + cell) & (my < self.my.max() - cell)
        dem = dem.copy()
        dem[np.ix_(iny, inx)] -= 60.0
        self.outer_radius = float(max(np.ptp(mx), np.ptp(my))) * self.k / 2
        return self._mesh(pv, dem, mx, my, tex, text)

    def _mesh(self, pv, dem, mxs, mys, texim, text):
        mx, my = np.meshgrid(mxs, mys)                               # (ny, nx)
        X, Y = (mx - self.cx) * self.k, (my - self.cy) * self.k
        Z = dem * self.ex
        u = (mx - text[0]) / (text[1] - text[0])
        v = (my - text[2]) / (text[3] - text[2])
        grid = pv.StructuredGrid(X.T, Y.T, Z.T)                      # i = 東西、j = 南北
        grid.active_texture_coordinates = np.c_[u.T.ravel(order="F"), v.T.ravel(order="F")]
        grid = grid.extract_surface().compute_normals(point_normals=True, cell_normals=False,
                                                      split_vertices=False)
        tex = pv.Texture(np.ascontiguousarray(texim[::-1]))          # 影像第 0 列在北邊，VTK 以左下為原點
        tex.interpolate = True
        tex.mipmap = True
        return grid, tex


# ── 相機 ──────────────────────────────────────────────────
def smoothstep(t):
    t = np.clip(t, 0, 1)
    return t * t * (3 - 2 * t)


def gaussian(a, sigma):
    if sigma < 0.5:
        return a
    r = int(sigma * 3)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    pad = np.pad(a, ((r, r),) + ((0, 0),) * (a.ndim - 1), mode="edge")
    return np.stack([np.convolve(pad[:, i], k, mode="valid") for i in range(a.shape[1])], axis=1)


def camera_path(scene, s, fps, pitch=0.85, dist=1.0, n_outro=None, aspect=16 / 9, fov=50.0):
    """回傳每幀的 (相機位置, 焦點)：開場俯瞰 → 跟隨飛行 → 結尾拉高俯瞰。"""
    P = np.c_[scene.tx, scene.ty, scene.tz]
    d = scene.data["dists"] * 1000.0
    L = float(d[-1])
    ext = float(max(np.ptp(scene.tx), np.ptp(scene.ty), 1.0))
    back = float(np.clip(L * 0.10, 150, 1800)) * dist
    ahead = back * 0.15                                  # 注視點鎖定目前位置：小人固定在畫面中段（地平線靠較低的鏡頭角度帶出來）
    hgt = back * pitch + 40 * scene.ex                   # pitch 越小越水平，越能看出地形起伏

    # 鏡頭跟著「平滑過的路線」走：GPS 軌跡本身有小抖動，直接跟會讓畫面晃
    step = 2.0
    dd = np.arange(0.0, L + step, step)
    Pr = np.stack([np.interp(dd, d, P[:, i]) for i in range(3)], axis=1)
    Pr = gaussian(Pr, max(25.0, back * 0.15) / step)
    P, d = Pr, dd

    def P_at(s):
        s = np.asarray(s, float)
        out = np.empty((len(s), 3))
        for i in range(3):
            out[:, i] = np.interp(s, d, P[:, i])
        # 起點之前、終點之後沿首/末段方向延伸
        h0 = P[min(len(P) - 1, 8), :2] - P[0, :2]
        h0 /= (np.linalg.norm(h0) + 1e-9)
        h1 = P[-1, :2] - P[max(0, len(P) - 9), :2]
        h1 /= (np.linalg.norm(h1) + 1e-9)
        lo, hi = s < 0, s > L
        out[lo, :2] = P[0, :2] + h0 * s[lo, None]
        out[hi, :2] = P[-1, :2] + h1 * (s[hi, None] - L)
        return out

    s = np.asarray(s, float)
    frames = len(s)
    focal = P_at(s + ahead)
    # 鏡頭放在「平滑後的行進方向」正後方。不用「路線往回 N 公尺的點」，否則之字形折返時鏡頭會跑到小人前面回頭看
    here = P_at(s)
    hd = P_at(s + back * 0.6)[:, :2] - P_at(s - back * 0.6)[:, :2]
    hy = np.unwrap(np.arctan2(hd[:, 1], hd[:, 0]))
    hy = gaussian(hy[:, None], fps * 1.5)[:, 0]
    # 限制轉向速度（每秒最多 20°）：急轉彎、之字形路段時鏡頭慢慢繞過去，不會被甩出去造成晃動
    lim = math.radians(20) / fps
    for i in range(1, len(hy)):
        hy[i] = hy[i - 1] + np.clip(hy[i] - hy[i - 1], -lim, lim)
    hy = gaussian(hy[:, None], fps * 0.5)[:, 0]
    hd = np.c_[np.cos(hy), np.sin(hy)]
    cam = here.copy()
    cam[:, :2] = here[:, :2] - hd * back
    cam[:, 2] = here[:, 2] + hgt
    fpm = frames / max(L, 1.0)                           # 每公尺路線對應幾幀：平滑以「距離」計算，影片長短不影響追蹤
    sig = float(np.clip(back * 0.5 * fpm, fps * 0.6, fps * 1.5))
    cam, focal = gaussian(cam, sig), gaussian(focal, fps * 0.5)

    def env(v, w, sg):                                   # 往上包絡再平滑：保證夠高，又不會一格一格跳
        w = max(1, int(w))
        v = np.array([v[max(0, i - w):i + w + 1].max() for i in range(len(v))])
        return gaussian(v[:, None], max(1.0, sg))[:, 0]

    floor_z = env(scene.terrain_at(cam[:, 0], cam[:, 1]) + 60 * scene.ex, fps, fps * 0.8)
    cam[:, 2] = gaussian(np.maximum(cam[:, 2], floor_z)[:, None], fps * 0.8)[:, 0]
    cam[:, 2] = np.maximum(cam[:, 2], floor_z)

    # 視線遮擋：鏡頭 → 目前位置 之間若有山擋住，就把鏡頭拉高到看得見
    tgt = P_at(s)
    tgt[:, 2] += 10 * scene.ex
    ts = np.linspace(0.04, 0.9, 40)
    lx = cam[:, None, 0] * (1 - ts) + tgt[:, None, 0] * ts
    ly = cam[:, None, 1] * (1 - ts) + tgt[:, None, 1] * ts
    lz = cam[:, None, 2] * (1 - ts) + tgt[:, None, 2] * ts
    margin = 20 * scene.ex * (1 - ts)                    # 安全距離越接近目前位置越小，否則一直被判定「被擋住」而把鏡頭拉太高
    terr = scene.terrain_at(lx.ravel(), ly.ravel()).reshape(lx.shape) + margin
    need = np.max(np.maximum(0, terr - lz) / (1 - ts), axis=1)          # 鏡頭需要抬高多少
    cam[:, 2] += env(need, max(sig * 1.5, fps * 1.2), max(sig, fps * 0.8))

    # 總覽鏡頭：從南方斜上方看，距離依畫面比例算好，讓整條路線完整入鏡
    center = np.array([(scene.tx.min() + scene.tx.max()) / 2, (scene.ty.min() + scene.ty.max()) / 2,
                       float(np.mean(scene.tz))])
    radius = 0.5 * float(np.hypot(np.ptp(scene.tx), np.ptp(scene.ty))) * 1.6    # 留空間給儀表板
    vf = math.radians(fov)
    hf = 2 * math.atan(math.tan(vf / 2) * aspect)
    D = radius / math.tan(min(vf, hf) / 2)
    el = math.radians(62)
    ov_cam = center + np.array([0.0, -D * math.cos(el), D * math.sin(el)])
    ov_cam[2] = max(ov_cam[2], scene.tz.max() + 0.3 * radius)
    ov_foc = center

    n_in = max(24, int(frames * 0.12))
    n_out = n_outro if n_outro else max(24, int(frames * 0.12))   # 結尾：只在抵達終點後的那段拉遠
    ow = np.zeros(frames)                                         # 每幀「總覽」的比重（給畫面偏移用）
    for i in range(n_in):                                        # 開場：從總覽慢慢降到跟隨
        t = smoothstep(i / n_in)
        cam[i] = ov_cam * (1 - t) + cam[i] * t
        focal[i] = ov_foc * (1 - t) + focal[i] * t
        ow[i] = 1 - t
    for j in range(n_out):                                       # 結尾：拉回總覽
        i = frames - n_out + j
        t = smoothstep(j / max(1, n_out - 1))
        cam[i] = cam[i] * (1 - t) + ov_cam * t
        focal[i] = focal[i] * (1 - t) + ov_foc * t
        ow[i] = t
    return cam, focal, s, back, ow


# ── 地標 ──────────────────────────────────────────────────
class Landmarks:
    """地標（locationGPS.xlsx）：每幀投影到畫面上，被山擋住就淡出，走到附近時換成醒目顏色。"""

    def __init__(self, scene, items, lift):
        self.items = []
        for name, lat, lon, _dir in items:
            mx, my = merc(lon, lat)
            x, y = (float(mx) - scene.cx) * scene.k, (float(my) - scene.cy) * scene.k
            z = float(scene.terrain_at(np.array([x]), np.array([y]))[0])
            near = int(np.argmin((scene.tx - x) ** 2 + (scene.ty - y) ** 2))   # 軌跡上最接近的點
            self.items.append(dict(name=str(name).replace("\\n", "\n"), x=x, y=y, z=z + lift,
                                   near=near, alpha=0.0))
        self.scene = scene

    def visible(self, cam, it):
        ts = np.linspace(0.05, 0.95, 30)
        lx = cam[0] * (1 - ts) + it["x"] * ts
        ly = cam[1] * (1 - ts) + it["y"] * ts
        lz = cam[2] * (1 - ts) + it["z"] * ts
        return bool(np.all(self.scene.terrain_at(lx, ly) < lz))

    def draw(self, img, ren, cam, idx, W, H, scale):
        im = Image.fromarray(img)
        dr = ImageDraw.Draw(im, "RGBA")
        placed = []
        order = sorted(self.items, key=lambda it: -((it["x"] - cam[0]) ** 2 + (it["y"] - cam[1]) ** 2))
        for it in order:                                         # 遠的先畫，近的蓋在上面
            ren.SetWorldPoint(it["x"], it["y"], it["z"], 1.0)
            ren.WorldToDisplay()
            dx, dy, dz = ren.GetDisplayPoint()
            sx, sy = dx, H - dy
            on = 0 < dz < 1 and -50 < sx < W + 50 and 0 < sy < H * 0.78 and self.visible(cam, it)
            it["alpha"] += ((1.0 if on else 0.0) - it["alpha"]) * 0.25    # 淡入淡出
            a = it["alpha"]
            if a < 0.03:
                continue
            here = abs(idx - it["near"]) <= max(3, len(self.scene.tx) // 60)
            passed = idx > it["near"]
            fnt = g.PIL_FONT if here else g.PIL_FONT_SM
            lines = it["name"].split("\n")
            tw = max(dr.textlength(t, font=fnt) for t in lines)
            lh = fnt.size * 1.2
            bw, bh = tw + 16 * scale, lh * len(lines) + 10 * scale
            stem = 38 * scale
            bx0, by1 = sx - bw / 2, sy - stem
            box = [bx0, by1 - bh, bx0 + bw, by1]
            if any(not (box[2] < p[0] or box[0] > p[2] or box[3] < p[1] or box[1] > p[3]) for p in placed):
                continue                                         # 跟已畫的標籤重疊就略過
            placed.append(box)
            fill = (233, 69, 96, int(235 * a)) if here else ((40, 45, 70, int(200 * a)) if passed
                                                              else (15, 20, 40, int(200 * a)))
            dr.line([(sx, sy), (sx, by1)], fill=(255, 255, 255, int(220 * a)), width=max(2, int(2 * scale)))
            r = 5 * scale
            dr.ellipse([sx - r, sy - r, sx + r, sy + r], fill=(255, 224, 102, int(255 * a)),
                       outline=(30, 30, 30, int(200 * a)))
            dr.rounded_rectangle(box, radius=8 * scale, fill=fill,
                                 outline=(255, 224, 102, int(230 * a)) if here else None, width=2)
            for k, t in enumerate(lines):
                col = (255, 255, 255, int(255 * a)) if k == 0 else (200, 205, 225, int(255 * a))
                dr.text((sx, by1 - bh + 5 * scale + lh * k), t, font=fnt, fill=col, anchor="ma")
        return np.asarray(im)


# ── 登山小人 ──────────────────────────────────────────────
def _mat(R=None, t=(0, 0, 0), sc=1.0):
    M = np.eye(4)
    if R is not None:
        M[:3, :3] = R
    M[:3, :3] *= sc
    M[:3, 3] = t
    return M


def _rz(a):
    c, s_ = math.cos(a), math.sin(a)
    return np.array([[c, -s_, 0], [s_, c, 0], [0, 0, 1]])


def _ry(a):                                              # 繞左右軸（y）擺動：腳、手臂前後擺
    c, s_ = math.cos(a), math.sin(a)
    return np.array([[c, 0, s_], [0, 1, 0], [-s_, 0, c]])


class Hiker:
    """用簡單幾何組成的登山者：登山帽、外套、背包、長褲、登山鞋、兩支登山杖。
    區域座標：x = 前方、y = 左方、z = 上方，身高約 1.8 單位，再整體放大到在畫面中看得清楚。"""
    JACKET, PANTS, BOOT, SKIN, HAT = "#e8572a", "#3a4150", "#5a3a22", "#f0c8a0", "#2f6b4f"
    PACK, PACK2, POLE = "#2b6cb0", "#1f4f85", "#c9ced6"

    def __init__(self, pl, pv, size):
        self.S = size / 1.8
        self.parts = []                                  # (actor, 局部 4x4, 擺動類型)

        def add(mesh, color, kind=None, pivot=(0, 0, 0)):
            act = pl.add_mesh(mesh, color=color, smooth_shading=True, ambient=0.35, diffuse=0.8)
            self.parts.append((act, np.array(pivot, float), kind))

        # 腳（從髖關節往下），各自繞髖關節擺動
        for side, kind in ((0.11, "legL"), (-0.11, "legR")):
            add(pv.Cylinder(center=(0, 0, -0.42), direction=(0, 0, 1), radius=0.085, height=0.84), self.PANTS,
                kind, (0, side, 0.95))
            add(pv.Box(bounds=(-0.06, 0.2, -0.07, 0.07, -0.95, -0.82)), self.BOOT, kind, (0, side, 0.95))
        # 身體、頭、帽子、背包（固定）
        add(pv.Cylinder(center=(0, 0, 1.25), direction=(0, 0, 1), radius=0.2, height=0.62), self.JACKET)
        add(pv.Sphere(radius=0.13, center=(0.02, 0, 1.7)), self.SKIN)
        add(pv.Cylinder(center=(0.02, 0, 1.79), direction=(0, 0, 1), radius=0.15, height=0.07), self.HAT)
        add(pv.Cylinder(center=(0.02, 0, 1.84), direction=(0, 0, 1), radius=0.1, height=0.1), self.HAT)
        add(pv.Box(bounds=(-0.46, -0.16, -0.19, 0.19, 0.98, 1.62)), self.PACK)
        add(pv.Cylinder(center=(-0.31, 0, 1.68), direction=(0, 1, 0), radius=0.09, height=0.36), self.PACK2)  # 睡墊
        # 手臂 + 登山杖（從肩膀往下），與同側的腳反向擺動
        for side, kind in ((0.25, "armL"), (-0.25, "armR")):
            add(pv.Cylinder(center=(0.05, 0, -0.3), direction=(0.15, 0, -1), radius=0.06, height=0.6), self.JACKET,
                kind, (0, side, 1.5))
            add(pv.Cylinder(center=(0.32, 0, -0.78), direction=(0.35, 0, -1), radius=0.02, height=1.15), self.POLE,
                kind, (0, side, 1.5))
        self.shadow = pl.add_mesh(pv.Disc(inner=0, outer=0.55, c_res=32), color="black", opacity=0.35, lighting=False)
        self.phase = 0.0

    def update(self, pos, yaw, walking, fps):
        if walking:
            self.phase += 2 * math.pi * 1.0 / fps        # 每秒一個步伐週期（左右各一步）
        sw = math.sin(self.phase) * (0.45 if walking else 0.0)
        ang = {"legL": sw, "legR": -sw, "armL": -sw * 0.8, "armR": sw * 0.8}
        bob = abs(math.cos(self.phase)) * 0.04 if walking else 0.0
        W = _mat(_rz(yaw), t=(pos[0], pos[1], pos[2] + bob * self.S), sc=self.S)
        for act, pivot, kind in self.parts:
            if kind:
                L = _mat(t=pivot) @ _mat(_ry(ang[kind]))
            else:
                L = np.eye(4)
            act.user_matrix = W @ L
        self.shadow.user_matrix = _mat(t=(pos[0], pos[1], pos[2] + 0.02 * self.S), sc=self.S)


# ── HUD ───────────────────────────────────────────────────
DASH_LABELS = ["距離", "海拔", "↑上坡", "↓下坡"]                 # 與 2D 模式相同
DASH_COLORS = [(255, 200, 100), (130, 200, 255), (255, 130, 100), (130, 220, 200)]   # #ffc864 #82c8ff #ff8264 #82dcc8
PANEL_RGBA = (15, 25, 50, 175)                                    # 2D 的 #0f1932，改成半透明
LABEL_COL, UNIT_COL, TEXT_COL = (200, 200, 224), (180, 180, 200), (234, 234, 234)
PROFILE_BASE, DONE_COL, ACCENT_COL = (68, 68, 102), (245, 166, 35), (233, 69, 96)


def _nice_step(span):
    for st in (10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000):
        if span / st <= 6:
            return st
    return 5000


def draw_hud(frame, data, idx, width, height, title, credit, prof):
    im = Image.fromarray(frame).convert("RGBA")
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(ov)
    sc = min(width, height) / 720
    pad = int(min(width, height) * 0.035)
    land = width > height
    big, mid, sm = g.PIL_FONT_BIG, g.PIL_FONT, g.PIL_FONT_SM

    # 標題
    tw = dr.textlength(title, font=big)
    t_bottom = pad + big.size * 1.9
    dr.rounded_rectangle([pad, pad, pad + tw + pad, t_bottom], radius=int(12 * sc), fill=PANEL_RGBA)
    dr.text((pad * 1.5, pad + big.size * 0.35), title, font=big, fill=(255, 255, 255, 255))

    lh = sm.size * 1.3
    gap = int(8 * sc)
    cell_h = big.size + sm.size * 3.4
    cells = []                                             # 4 格儀表板的位置 (x0, y0, 寬)
    if land:
        # 橫式：儀表板（2×2）＋高度剖面縮成左下角一塊（寬約 1/3，與 2D 橫式的左欄相近），畫面其餘留給 3D
        bw = int(width * 0.34)
        left, right = pad, pad + bw
        py1 = height - pad
        py0 = py1 - int(height * 0.21)
        r2 = py0 - gap - cell_h
        r1 = r2 - gap - cell_h
        cw = (bw - gap) / 2
        cells = [(left, r1, cw), (left + cw + gap, r1, cw), (left, r2, cw), (left + cw + gap, r2, cw)]
    else:
        # 直式（與 2D 直式相同的分配）：數字列在最上方（標題下），高度剖面在最下方，合計約 28% 高度，中間留給 3D
        left, right = pad, width - pad
        cw = ((right - left) - gap * 3) / 4
        r1 = t_bottom + gap
        cells = [(left + k * (cw + gap), r1, cw) for k in range(4)]
        py1 = height - pad * 0.7 - lh * len(credit)
        py0 = py1 - int(height * 0.20)

    # ── 儀表板：4 格，左側色條＋標籤＋彩色數字（2D 模板） ──
    i = int(idx)
    e = data["eles"]
    items = [(f"{data['dists'][i]:.2f}", f"/ {data['total_dist']:.1f} km", None),
             (f"{e[i]:.0f}", "m", f"▲{data['ele_max']:.0f}  ▼{data['ele_min']:.0f} m"),
             (f"{prof['gain'][i]:.0f}", f"/ {prof['gain'][-1]:.0f} m", None),
             (f"{prof['loss'][i]:.0f}", f"/ {prof['loss'][-1]:.0f} m", None)]
    for ((val, unit, sub), lab, col, (x0, y0, cw_)) in zip(items, DASH_LABELS, DASH_COLORS, cells):
        dr.rounded_rectangle([x0, y0, x0 + cw_, y0 + cell_h], radius=int(8 * sc), fill=PANEL_RGBA)
        dr.rectangle([x0, y0 + 4 * sc, x0 + max(3, 5 * sc), y0 + cell_h - 4 * sc], fill=col + (255,))
        tx = x0 + 12 * sc
        dr.text((tx, y0 + 6 * sc), lab, font=sm, fill=LABEL_COL + (255,))
        vy = y0 + 6 * sc + sm.size * 1.25
        fb = big
        while dr.textlength(val, font=fb) + dr.textlength(unit, font=sm) + 18 * sc > cw_ and fb.size > 10:
            fb = fb.font_variant(size=fb.size - 1)
        dr.text((tx, vy), val, font=fb, fill=col + (255,))
        vw = dr.textlength(val, font=fb)
        dr.text((tx + vw + 4 * sc, vy + fb.size - sm.size), unit, font=sm, fill=UNIT_COL + (255,))
        if sub:
            dr.text((tx, vy + fb.size * 1.12), sub, font=sm, fill=(140, 170, 210, 255))

    # ── 高度剖面（2D 模板：標題、座標軸、虛線格線、已走區段填色、目前位置） ──
    dr.rounded_rectangle([pad, py0, right, py1], radius=int(10 * sc), fill=PANEL_RGBA)
    dr.text(((pad + right) / 2, py0 + 4 * sc), "高度剖面", font=mid, fill=TEXT_COL + (255,), anchor="ma")
    ax0 = pad + dr.textlength("0000", font=sm) + 18 * sc                 # 繪圖區
    ax1 = right - 12 * sc
    ay0 = py0 + mid.size * 1.5
    ay1 = py1 - sm.size * 1.9
    emin, emax = data["ele_min"], data["ele_max"]
    ypad = (emax - emin) * 0.12 + 20
    lo, hi = emin - ypad, emax + ypad
    D = max(data["dists"][-1], 1e-6)
    X = lambda d: ax0 + (ax1 - ax0) * d / D
    Y = lambda v: ay1 - (ay1 - ay0) * (v - lo) / (hi - lo)
    step = _nice_step(hi - lo)
    v = math.ceil(lo / step) * step
    while v <= hi:                                                     # 海拔虛線格線＋刻度
        yy = Y(v)
        for xx in np.arange(ax0, ax1, 7 * sc):
            dr.line([(xx, yy), (min(xx + 4 * sc, ax1), yy)], fill=(136, 136, 170, 115), width=1)
        dr.text((ax0 - 6 * sc, yy), f"{v:.0f}", font=sm, fill=TEXT_COL + (255,), anchor="rm")
        v += step
    kstep = next(st for st in (0.5, 1, 2, 2.5, 5, 10, 20, 25, 50) if D / st <= 8)
    kv = 0.0
    while kv <= D + 1e-9:                                              # 距離刻度
        dr.text((X(kv), ay1 + 4 * sc), f"{kv:g}", font=sm, fill=TEXT_COL + (255,), anchor="ma")
        kv += kstep
    dr.text((ax1, ay1 + 4 * sc), "km", font=sm, fill=UNIT_COL + (255,), anchor="ra")
    dr.line([(ax0, ay0), (ax0, ay1), (ax1, ay1)], fill=(42, 42, 74, 255), width=1)
    n = len(e)
    stepi = max(1, n // 500)
    pts = [(X(data["dists"][j]), Y(e[j])) for j in range(0, n, stepi)] + [(X(data["dists"][-1]), Y(e[-1]))]
    dr.polygon(pts + [(pts[-1][0], ay1), (pts[0][0], ay1)], fill=PROFILE_BASE + (90,))
    dr.line(pts, fill=PROFILE_BASE + (255,), width=max(1, int(1.5 * sc)))
    done = [(X(data["dists"][j]), Y(e[j])) for j in range(0, i + 1, stepi)] + [(X(data["dists"][i]), Y(e[i]))]
    if len(done) > 1:
        dr.polygon(done + [(done[-1][0], ay1), (done[0][0], ay1)], fill=DONE_COL + (140,))
        dr.line(done, fill=DONE_COL + (255,), width=max(2, int(3 * sc)))
    cx, cy = X(data["dists"][i]), Y(e[i])
    dr.line([(cx, ay0), (cx, ay1)], fill=ACCENT_COL + (255,), width=max(1, int(2 * sc)))
    r1, r2 = 7 * sc, 4 * sc
    dr.ellipse([cx - r1, cy - r1, cx + r1, cy + r1], fill=(255, 255, 255, 255))
    dr.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], fill=ACCENT_COL + (255,))
    lab = f"{e[i]:.0f} m"
    lx = cx + 10 * sc if cx + 10 * sc + dr.textlength(lab, font=sm) < ax1 else cx - 10 * sc - dr.textlength(lab, font=sm)
    dr.text((lx, cy - sm.size * 1.1), lab, font=sm, fill=TEXT_COL + (255,))

    # 來源標示
    cmax = (width - 2 * pad) if not land else (width - right - 2 * pad)      # 橫式：放在右下角，不壓到左下的儀表板
    cx1 = width - pad
    cy_base = (py1 + pad * 0.35 + lh * len(credit)) if not land else (height - pad * 0.5)
    lines = []
    for line in credit:
        fnt = sm
        while dr.textlength(line, font=fnt) > cmax and fnt.size > 8:
            fnt = fnt.font_variant(size=fnt.size - 1)
        lines.append((line, fnt, dr.textlength(line, font=fnt)))
    bx0 = cx1 - max(w for _, _, w in lines) - 8 * sc
    by1 = cy_base + 3 * sc
    by0 = cy_base - lh * (len(credit) - 1) - lh * 0.95
    dr.rounded_rectangle([bx0, by0, cx1 + 6 * sc, by1], radius=int(6 * sc), fill=(10, 15, 30, 150))   # 底色：亮色地形上也看得清楚
    for k, (line, fnt, _) in enumerate(lines):
        dr.text((cx1, cy_base - lh * (len(credit) - 1 - k) - lh * 0.25), line, font=fnt,
                fill=(255, 255, 255, 235), anchor="rs")
    return np.asarray(Image.alpha_composite(im, ov).convert("RGB"))


def slope_colors(data):
    n = len(data["lats"])
    e, d = data["eles"], data["dists"]
    out = np.zeros((n, 3), np.uint8)
    for i in range(n):
        i0, i1 = max(0, i - 3), min(n - 1, i + 3)
        grade = (float(e[i1] - e[i0]) / (float(d[i1] - d[i0]) * 1000 + 1e-3)) * 100 if 0 < i < n - 1 else 0
        b, gg, r = g.slope_color_bgr(grade)
        out[i] = (r, gg, b)
    return out


# ── 主流程 ────────────────────────────────────────────────
HAZE_HEX = "#c8d8e8"
HAZE_RGB = np.array([200, 216, 232], np.float32)


def render(args, progress=None):
    import pyvista as pv
    global vtkFloatArray, vtk_to_numpy
    from vtkmodules.vtkCommonCore import vtkFloatArray
    from vtkmodules.util.numpy_support import vtk_to_numpy
    global cv2
    import cv2
    pv.global_theme.multi_samples = 4
    data = g.parse_gpx(args.gpx)
    if args.title:
        data["track_name"] = args.title
    n = len(data["lats"])
    print(f"   軌跡：{data['track_name']}，{n} 點，{data['total_dist']:.2f} km，"
          f"{data['ele_min']:.0f}~{data['ele_max']:.0f} m")
    tinfo = TEXTURES[args.texture]
    print(f"   貼圖：{tinfo['label']}（{tinfo['license']}）")
    if tinfo.get("notice"):
        print("   " + tinfo["notice"])
    scene = Scene(data, args.texture, args.exaggeration)

    W, H = args.width + args.width % 2, args.height + args.height % 2
    g.scale_fonts_for(W, H, W > H)
    frames_move = max(120, int(args.seconds * args.fps))
    sat = args.texture.startswith("s2")                     # 10 m 衛星：鏡頭拉遠；Esri 高解析可以拉近
    dist = args.cam_dist if args.cam_dist is not None else (2.2 if sat else 0.6)     # 衛星影像 10 m 解析度，遠一點比較清楚
    pitch = args.pitch if args.pitch is not None else (1.0 if sat else 0.42)
    lm = None
    lm_path = args.landmarks
    if lm_path is None:                                          # 預設：程式旁的 locationGPS.xlsx
        base = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
        cand = os.path.join(base, "locationGPS.xlsx")
        lm_path = cand if os.path.isfile(cand) else None
    if lm_path and not args.no_landmarks:
        items = g.load_landmarks(lm_path, args.radius, data["lats"], data["lons"])
        if items:
            lm = Landmarks(scene, items, lift=15 * scene.ex)

    # 地標照片：地標庫的「照片」欄，或照片資料夾裡與地標同名的圖片
    holds = []
    if lm and not args.no_photos:
        table = landmark_photo_table(lm_path)
        folder = args.photos or default_folder(lm_path)
        hold_n = max(1, int(round(args.photo_seconds * args.fps)))
        for it in lm.items:
            ph = find_photo(it["name"], table, folder)
            if ph:
                try:
                    card = PhotoCard(ph, it["name"], W, H, min(W, H) / 720, g.PIL_FONT)
                except Exception as ex:
                    print(f"   ⚠️  照片無法開啟：{ph}（{ex}）")
                    continue
                holds.append((float(data["dists"][it["near"]] * 1000.0), hold_n, card))
        if holds:
            print(f"   🖼️  地標照片：{len(holds)} 張，每張停留 {args.photo_seconds:g} 秒")
    s_sched, photo_ranges = build_schedule(float(data["dists"][-1] * 1000.0), frames_move, holds)
    # 結尾：小人走到終點、停下約 0.5 秒後，鏡頭才慢慢拉遠（預設 4 秒）讓整段軌跡入鏡
    n_pause = int(round(args.fps * 0.5))
    n_outro = max(1, int(round(args.fps * args.outro_seconds)))
    s_sched = np.concatenate([s_sched, np.full(n_pause + n_outro, s_sched[-1])])
    frames = len(s_sched)
    cam, focal, s, back, ow = camera_path(scene, s_sched, args.fps, pitch, dist,
                                          n_outro=n_outro, aspect=W / H, fov=args.fov)
    idx_f = np.interp(s, data["dists"] * 1000.0, np.arange(n))
    photo_at = {}
    hold_w = np.zeros(frames)
    for a, b, card in photo_ranges:
        for f in range(a, b):
            photo_at[f] = (card, (f - a) / max(1, b - a - 1), f - a, b - a)
            hold_w[f] = 1.0
    hold_w = np.clip(gaussian(hold_w[:, None], max(1.0, args.fps * 0.3))[:, 0] * 1.25, 0, 1)   # 平順進出

    print("\n🏔️  建立 3D 地形...")
    mesh, tex = scene.build_mesh(pv)
    pl = pv.Plotter(off_screen=True, window_size=(W, H))
    pl.set_background(HAZE_HEX, top="#2d5b97")
    pl.add_mesh(mesh, texture=tex, smooth_shading=True, ambient=0.42, diffuse=0.75, specular=0.0)
    outer_r = None
    if not args.no_outer:
        try:
            omesh, otex = scene.build_outer(pv)
            pl.add_mesh(omesh, texture=otex, smooth_shading=True, ambient=0.42, diffuse=0.75, specular=0.0)
            outer_r = scene.outer_radius
        except Exception as ex:
            print(f"   ⚠️  外圍地形下載失敗（{ex}），只顯示主地形")
    pl.remove_all_lights()
    ext = float(max(np.ptp(scene.tx), np.ptp(scene.ty)))
    light = pv.Light(position=(-ext, ext, scene.tz.max() + ext * 0.7), focal_point=(0, 0, 0),
                     color="white", intensity=0.9)
    light.positional = False
    pl.add_light(light)

    colors = slope_colors(data)
    route = pv.PolyData(np.c_[scene.tx, scene.ty, scene.tz + 6 * scene.ex])
    route.lines = np.hstack([[n], np.arange(n)]).astype(np.int64)
    rgb = np.tile(np.array([230, 230, 255, 120], np.uint8), (n, 1))
    route.point_data["rgb"] = rgb.copy()
    pl.add_mesh(route, scalars="rgb", rgb=True, line_width=args.line_width,
                render_lines_as_tubes=True, lighting=False, name="route")
    rad = max(6.0, back * 0.022)                         # 依鏡頭距離決定大小，拉遠時也看得到
    hiker = mact = hact = None
    if args.marker == "hiker":
        hiker = Hiker(pl, pv, size=max(12.0, back * 0.06))
        # 行進方向：用前後各一小段的軌跡算朝向，再平滑，避免小人抖動
        hx = np.interp(s + 15, data["dists"] * 1000.0, scene.tx) - np.interp(s - 15, data["dists"] * 1000.0, scene.tx)
        hy = np.interp(s + 15, data["dists"] * 1000.0, scene.ty) - np.interp(s - 15, data["dists"] * 1000.0, scene.ty)
        yaw = np.unwrap(np.arctan2(hy, hx))
        yaw = gaussian(yaw[:, None], max(1.0, args.fps * 0.25))[:, 0]
    else:
        marker = pv.Sphere(radius=rad, theta_resolution=24, phi_resolution=24)
        mact = pl.add_mesh(marker, color="#ff3b5c", lighting=False)
        halo = pv.Sphere(radius=rad * 1.45, theta_resolution=24, phi_resolution=24)
        hact = pl.add_mesh(halo, color="white", opacity=0.45, lighting=False)
    pl.camera.view_angle = args.fov
    pl.camera.SetWindowCenter(0.0, args.shift)      # 負值 = 把畫面往上推，讓目前位置不被下方儀表板蓋住

    prof = dict(gain=np.concatenate([[0], np.cumsum(np.maximum(0, np.diff(data["eles"])))]),
                loss=np.concatenate([[0], np.cumsum(np.maximum(0, -np.diff(data["eles"])))]))
    credit = TEXTURES[args.texture]["credit"] + [TERRAIN_CREDIT]

    out = args.output or os.path.splitext(os.path.basename(args.gpx))[0] + f" 3D ({W}x{H}).mp4"
    enc, hw = g.detect_encoder()
    ff = g.find_ffmpeg()
    if ff is None:
        try:
            import imageio_ffmpeg
            ff = imageio_ffmpeg.get_ffmpeg_exe()
            enc, hw = "libx264", "CPU"
        except Exception:
            ff = None
    proc = cv_out = None
    if ff:
        if args.no_gpu:
            enc = "libx264"
        cmd = [ff, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(args.fps),
               "-i", "-", "-c:v", enc or "libx264"]
        cmd += (["-preset", "p4", "-rc", "vbr", "-cq", "26", "-b:v", "0"] if enc == "h264_nvenc"
                else ["-preset", "veryfast", "-crf", "22"])
        cmd += ["-pix_fmt", "yuv420p", out]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=_NOWIN)
    else:
        print("   ⚠️  找不到 ffmpeg，改用內建編碼（相容性較低）")
        enc = "mp4v"
        cv_out = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (W, H))

    print(f"🎬 {W}×{H}，{frames} 幀（{frames / args.fps:.0f} 秒），編碼 {enc}")
    t0 = time.time()
    haze_img = None
    for f in range(frames):
        i = int(round(idx_f[f]))
        r = route.point_data["rgb"]
        r[:i + 1, :3] = colors[:i + 1]
        r[:i + 1, 3] = 255
        r[i + 1:] = (230, 230, 255, 110)
        route.point_data["rgb"] = r
        if hiker:
            fi = idx_f[f]
            pz = float(np.interp(fi, np.arange(n), scene.tz))
            pos = (float(np.interp(fi, np.arange(n), scene.tx)), float(np.interp(fi, np.arange(n), scene.ty)), pz)
            hiker.update(pos, float(yaw[f]), f not in photo_at and 0 < fi < n - 1, args.fps)
        else:
            mp = (float(scene.tx[i]), float(scene.ty[i]), float(scene.tz[i] + rad * 0.8))
            mact.SetPosition(*mp)
            hact.SetPosition(*mp)
        # 停留看照片時把畫面平順地移開，小人不被照片卡片擋住（橫式往左、直式往下）
        hw = hold_w[f]
        o = float(ow[f])                    # 開場/結尾總覽：把整段路線移到儀表板以外的空白區域
        if W > H:
            pl.camera.SetWindowCenter(0.32 * hw - 0.44 * o, args.shift - 0.06 * o)
        else:
            pl.camera.SetWindowCenter(0.0, args.shift + 0.55 * hw - 0.3 * o)
        pl.camera.position = tuple(cam[f])
        pl.camera.focal_point = tuple(focal[f])
        pl.camera.up = (0, 0, 1)
        pl.camera.clipping_range = (5.0, (outer_r or ext) * 6 + 20000)
        pl.render()
        img = pl.screenshot(return_img=True)
        if outer_r and not args.no_haze:                       # 大氣霧化：越遠越淡，地平線自然融入天空
            zb = vtkFloatArray()
            pl.ren_win.GetZbufferData(0, 0, W - 1, H - 1, zb)           # 直接讀深度緩衝區（不必再渲染一次）
            z = vtk_to_numpy(zb).reshape(H, W)[::-2, ::2].astype(np.float32)   # 半解析度計算就夠（霧是平滑的）
            near, far = pl.camera.clipping_range
            ndc = 2.0 * z - 1.0
            d = 2.0 * near * far / (far + near - ndc * (far - near))
            start, full = outer_r * 0.35, outer_r * 1.6
            fog = np.clip((d - start) / (full - start), 0, 1) ** 1.3 * 0.75
            fog[z >= 0.99999] = 0                                     # 天空
            fog = cv2.resize(fog.astype(np.float32), (W, H), interpolation=cv2.INTER_LINEAR)
            if haze_img is None:
                haze_img = np.empty_like(img)
                haze_img[:] = HAZE_RGB.astype(np.uint8)
            img = cv2.blendLinear(img, haze_img, 1.0 - fog, fog)
        if lm:
            img = lm.draw(img, pl.renderer, cam[f], i, W, H, min(W, H) / 720)
        img = draw_hud(img, data, i, W, H, data["track_name"], credit, prof)
        if f in photo_at:
            card, u, k, nk = photo_at[f]
            fade = max(1, int(args.fps * 0.3))
            img = card.draw(img, u, min(1.0, (k + 1) / fade, (nk - k) / fade))
        if proc:
            proc.stdin.write(img.tobytes())
        else:
            cv_out.write(cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        if f % max(1, frames // 20) == 0:
            el = time.time() - t0
            if progress:
                progress(f / frames)
            else:
                print(f"   {f / frames * 100:5.1f}%  {f / max(el, 1e-3):.1f} 幀/s", end="\r")
    if proc:
        proc.stdin.close()
        proc.wait()
    if cv_out:
        cv_out.release()
    pl.close()
    print(f"\n✅ 完成：{out}（{time.time() - t0:.0f} 秒）")
    return out


def build_parser():
    ap = argparse.ArgumentParser(description="GPX → 3D 地形飛行影片")
    ap.add_argument("gpx")
    ap.add_argument("--title", default=None)
    ap.add_argument("--output", default=None)
    ap.add_argument("--texture", choices=list(TEXTURES), default="topo",
                    help="貼圖：topo / osm / s2-2016（衛星，CC BY 4.0）/ s2-2024（衛星，CC BY-NC-SA 4.0 僅限非商業）"
                         " / esri（高解析衛星，需自備 ArcGIS 金鑰）")
    ap.add_argument("--exaggeration", type=float, default=1.5, help="地形高度誇張倍率")
    ap.add_argument("--seconds", type=float, default=30, help="影片長度（秒）")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--width", type=int, default=720)
    ap.add_argument("--height", type=int, default=1280)
    ap.add_argument("--fov", type=float, default=50)
    ap.add_argument("--shift", type=float, default=-0.15, help="畫面垂直偏移（-1~1）")
    ap.add_argument("--pitch", type=float, default=None, help="跟隨鏡頭高度比（越大越俯視；預設 0.42，Sentinel-2 衛星 1.0）")
    ap.add_argument("--cam-dist", type=float, default=None, help="跟隨鏡頭距離倍率（預設 0.6，Sentinel-2 衛星 2.2）")
    ap.add_argument("--line-width", type=float, default=7)
    ap.add_argument("--no-gpu", action="store_true")
    ap.add_argument("--landmarks", default=None, help="地標庫（.xlsx / .csv），預設使用程式旁的 locationGPS.xlsx")
    ap.add_argument("--radius", type=float, default=0.5, help="地標篩選半徑（公里）")
    ap.add_argument("--no-landmarks", action="store_true", help="不顯示地標")
    ap.add_argument("--photos", default=None,
                    help="地標照片資料夾（檔名 = 地標名稱，例如 第一山屋.jpg）；預設為地標庫旁的 landmark_photos")
    ap.add_argument("--photo-seconds", type=float, default=3.0, help="每張地標照片停留秒數（建議 2.5~3.5）")
    ap.add_argument("--no-photos", action="store_true", help="不顯示地標照片")
    ap.add_argument("--no-outer", action="store_true", help="不加外圍地形")
    ap.add_argument("--no-haze", action="store_true", help="不加遠景霧化")
    ap.add_argument("--marker", choices=["hiker", "dot"], default="hiker", help="目前位置標記：登山小人或紅點")
    ap.add_argument("--outro-seconds", type=float, default=4.0, help="抵達終點後鏡頭拉遠的秒數（建議 3~5）")
    return ap


def main():
    render(build_parser().parse_args())


if __name__ == "__main__":
    main()
