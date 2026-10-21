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

UA = g.HIKEREEL_UA if getattr(g, "HAS_CTX", False) else "HikeReel/1.1 (+https://github.com/skypray73/HikeReel)"
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


def fetch_esri(xmin, ymin, xmax, ymax, max_tiles):
    """Esri World Imagery：圖磚依 HTTP 標頭最多暫存 24 小時，同一天重做不必重新下載，過期自動刪除。"""
    from concurrent.futures import ThreadPoolExecutor
    import io
    key = arcgis_key()
    if not key:
        sys.exit("❌ 找不到 ArcGIS 金鑰。請先在 PowerShell 執行：setx ARCGIS_API_KEY \"你的金鑰\"")
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


def fetch_texture(xmin, ymin, xmax, ymax, source="topo", max_tiles=100):
    if source == "esri":
        return fetch_esri(xmin, ymin, xmax, ymax, max_tiles=1200)    # 高解析：最多約 1200 張（免費額度每月 200 萬張）
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

        # 只保留貼圖與高程都涵蓋的範圍
        ix0, ix1 = max(dext[0], text[0]), min(dext[2], text[1])
        iy0, iy1 = max(dext[1], text[2]), min(dext[3], text[3])
        px, py = (dext[2] - dext[0]) / dem.shape[1], (dext[3] - dext[1]) / dem.shape[0]
        c0, c1 = int(math.ceil((ix0 - dext[0]) / px)), int((ix1 - dext[0]) / px)
        r0, r1 = int(math.ceil((dext[3] - iy1) / py)), int((dext[3] - iy0) / py)
        dem = dem[r0:r1, c0:c1]
        self.mx = dext[0] + (np.arange(c0, c1) + 0.5) * px           # 每欄的 Web Mercator x
        self.my = dext[3] - (np.arange(r0, r1) + 0.5) * py           # 每列的 y（由北到南）
        self.dem = dem
        self.tex, self.text = tex, text

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
        mx, my = np.meshgrid(self.mx, self.my)                       # (ny, nx)
        X, Y = (mx - self.cx) * self.k, (my - self.cy) * self.k
        Z = self.dem * self.ex
        u = (mx - self.text[0]) / (self.text[1] - self.text[0])
        v = (my - self.text[2]) / (self.text[3] - self.text[2])
        grid = pv.StructuredGrid(X.T, Y.T, Z.T)                      # i = 東西、j = 南北
        grid.active_texture_coordinates = np.c_[u.T.ravel(order="F"), v.T.ravel(order="F")]
        grid = grid.extract_surface().compute_normals(point_normals=True, cell_normals=False,
                                                      split_vertices=False)
        tex = pv.Texture(np.ascontiguousarray(self.tex[::-1]))       # 影像第 0 列在北邊，VTK 以左下為原點
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


def camera_path(scene, frames, fps, pitch=0.85, dist=1.0):
    """回傳每幀的 (相機位置, 焦點)：開場俯瞰 → 跟隨飛行 → 結尾拉高俯瞰。"""
    P = np.c_[scene.tx, scene.ty, scene.tz]
    d = scene.data["dists"] * 1000.0
    L = float(d[-1])
    ext = float(max(np.ptp(scene.tx), np.ptp(scene.ty), 1.0))
    back = float(np.clip(L * 0.10, 150, 1800)) * dist
    ahead = back * 0.3                                   # 注視點貼近目前位置，紅點固定在畫面中段
    hgt = back * pitch + 90 * scene.ex

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

    s = np.linspace(0, L, frames)
    focal = P_at(s + ahead)
    cam = P_at(s - back)
    cam[:, 2] = np.maximum(cam[:, 2] + hgt, P_at(s)[:, 2] + hgt)
    fpm = frames / max(L, 1.0)                           # 每公尺路線對應幾幀：平滑以「距離」計算，影片長短不影響追蹤
    sig = float(np.clip(back * 0.5 * fpm, 1, fps * 1.5))
    cam, focal = gaussian(cam, sig), gaussian(focal, float(np.clip(back * 0.15 * fpm, 1, fps)))
    cam[:, 2] = np.maximum(cam[:, 2], scene.terrain_at(cam[:, 0], cam[:, 1]) + 60 * scene.ex)

    # 視線遮擋：鏡頭 → 目前位置 之間若有山擋住，就把鏡頭拉高到看得見
    tgt = P_at(s)
    tgt[:, 2] += 10 * scene.ex
    ts = np.linspace(0.04, 0.96, 40)
    lx = cam[:, None, 0] * (1 - ts) + tgt[:, None, 0] * ts
    ly = cam[:, None, 1] * (1 - ts) + tgt[:, None, 1] * ts
    lz = cam[:, None, 2] * (1 - ts) + tgt[:, None, 2] * ts
    terr = scene.terrain_at(lx.ravel(), ly.ravel()).reshape(lx.shape) + 25 * scene.ex
    need = np.max(np.maximum(0, terr - lz) / (1 - ts), axis=1)          # 鏡頭需要抬高多少
    win = max(1, int(sig * 1.5))
    need = np.array([need[max(0, i - win):i + win + 1].max() for i in range(len(need))])
    cam[:, 2] += gaussian(need[:, None], max(1.0, sig * 0.6))[:, 0]

    # 總覽鏡頭（從南方看向北方，高處）
    center = np.array([np.mean(scene.tx), np.mean(scene.ty), np.mean(scene.tz)])
    ov_cam = center + np.array([0.0, -1.25 * ext, 0.95 * ext])
    ov_cam[2] = max(ov_cam[2], scene.tz.max() + 0.5 * ext)
    ov_foc = center

    n_in = max(24, int(frames * 0.12))
    n_out = max(24, int(frames * 0.12))
    for i in range(n_in):                                        # 開場：從總覽慢慢降到跟隨
        t = smoothstep(i / n_in)
        cam[i] = ov_cam * (1 - t) + cam[i] * t
        focal[i] = ov_foc * (1 - t) + focal[i] * t
    for j in range(n_out):                                       # 結尾：拉回總覽
        i = frames - n_out + j
        t = smoothstep(j / max(1, n_out - 1))
        cam[i] = cam[i] * (1 - t) + ov_cam * t
        focal[i] = focal[i] * (1 - t) + ov_foc * t
    return cam, focal, s, back


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


# ── HUD ───────────────────────────────────────────────────
def draw_hud(frame, data, idx, width, height, title, credit, prof):
    im = Image.fromarray(frame)
    dr = ImageDraw.Draw(im, "RGBA")
    pad = int(min(width, height) * 0.035)
    # 標題
    tw = dr.textlength(title, font=g.PIL_FONT_BIG)
    dr.rounded_rectangle([pad, pad, pad + tw + pad, pad + g.PIL_FONT_BIG.size * 1.9],
                         radius=14, fill=(15, 20, 40, 170))
    dr.text((pad * 1.5, pad + g.PIL_FONT_BIG.size * 0.35), title, font=g.PIL_FONT_BIG, fill=(255, 255, 255, 255))
    # 數據
    i = int(idx)
    items = [("距離", f"{data['dists'][i]:.2f} km"), ("海拔", f"{data['eles'][i]:.0f} m"),
             ("累積上坡", f"{prof['gain'][i]:.0f} m"), ("累積下坡", f"{prof['loss'][i]:.0f} m")]
    bar_h = g.PIL_FONT_BIG.size * 2.6
    lh = g.PIL_FONT_SM.size * 1.3
    py1 = height - pad * 0.7 - lh * len(credit)
    py0 = py1 - height * 0.09
    y0 = py0 - pad * 0.6 - bar_h
    dr.rounded_rectangle([pad, y0, width - pad, y0 + bar_h], radius=16, fill=(15, 20, 40, 170))
    cw = (width - 2 * pad) / len(items)
    for k, (lab, val) in enumerate(items):
        x = pad + cw * k + cw / 2
        dr.text((x, y0 + bar_h * 0.18), val, font=g.PIL_FONT_BIG, fill=(255, 255, 255, 255), anchor="ma")
        dr.text((x, y0 + bar_h * 0.62), lab, font=g.PIL_FONT_SM, fill=(180, 190, 215, 255), anchor="ma")
    # 高度剖面
    dr.rounded_rectangle([pad, py0, width - pad, py1], radius=12, fill=(15, 20, 40, 150))
    xs = pad + (width - 2 * pad) * data["dists"] / max(data["dists"][-1], 1e-6)
    lo, hi = data["ele_min"], max(data["ele_max"], data["ele_min"] + 1)
    ys = py1 - 8 - (py1 - py0 - 16) * (data["eles"] - lo) / (hi - lo)
    pts = list(zip(xs[::max(1, len(xs) // 400)], ys[::max(1, len(xs) // 400)]))
    dr.line(pts, fill=(110, 110, 150, 255), width=3)
    done = [p for p, k in zip(pts, range(0, len(xs), max(1, len(xs) // 400))) if k <= i]
    if len(done) > 1:
        dr.line(done, fill=(245, 166, 35, 255), width=4)
    dr.ellipse([xs[i] - 7, ys[i] - 7, xs[i] + 7, ys[i] + 7], fill=(233, 69, 96, 255), outline=(255, 255, 255, 255))
    for k, line in enumerate(credit):
        fnt = g.PIL_FONT_SM
        while dr.textlength(line, font=fnt) > width - 2 * pad and fnt.size > 8:
            fnt = fnt.font_variant(size=fnt.size - 1)
        dr.text((width - pad, py1 + pad * 0.35 + lh * (k + 1) - lh * 0.25), line, font=fnt,
                fill=(255, 255, 255, 200), anchor="rs")
    return np.asarray(im)


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
def render(args):
    import pyvista as pv
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
    frames = max(120, int(args.seconds * args.fps))
    sat = args.texture.startswith("s2")                     # 10 m 衛星：鏡頭拉遠；Esri 高解析可以拉近
    dist = args.cam_dist if args.cam_dist is not None else (2.2 if sat else 1.0)     # 衛星影像 10 m 解析度，遠一點比較清楚
    pitch = args.pitch if args.pitch is not None else (1.0 if sat else 0.85)
    cam, focal, s, back = camera_path(scene, frames, args.fps, pitch, dist)
    idx_f = np.interp(s, data["dists"] * 1000.0, np.arange(n))

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

    print("\n🏔️  建立 3D 地形...")
    mesh, tex = scene.build_mesh(pv)
    pl = pv.Plotter(off_screen=True, window_size=(W, H))
    pl.set_background("#cfe3f4", top="#2d5b97")
    pl.add_mesh(mesh, texture=tex, smooth_shading=True, ambient=0.42, diffuse=0.75, specular=0.0)
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
            sys.exit("❌ 找不到 ffmpeg。請安裝：winget install Gyan.FFmpeg")
    if args.no_gpu:
        enc = "libx264"
    cmd = [ff, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(args.fps),
           "-i", "-", "-c:v", enc or "libx264"]
    cmd += (["-preset", "p4", "-rc", "vbr", "-cq", "26", "-b:v", "0"] if enc == "h264_nvenc"
            else ["-preset", "veryfast", "-crf", "22"])
    cmd += ["-pix_fmt", "yuv420p", out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print(f"🎬 {W}×{H}，{frames} 幀（{frames / args.fps:.0f} 秒），編碼 {enc}")
    t0 = time.time()
    done = np.array([0, 0, 0, 255], np.uint8)
    for f in range(frames):
        i = int(round(idx_f[f]))
        r = route.point_data["rgb"]
        r[:i + 1, :3] = colors[:i + 1]
        r[:i + 1, 3] = 255
        r[i + 1:] = (230, 230, 255, 110)
        route.point_data["rgb"] = r
        mp = (float(scene.tx[i]), float(scene.ty[i]), float(scene.tz[i] + rad * 0.8))
        mact.SetPosition(*mp)
        hact.SetPosition(*mp)
        pl.camera.position = tuple(cam[f])
        pl.camera.focal_point = tuple(focal[f])
        pl.camera.up = (0, 0, 1)
        pl.camera.clipping_range = (5.0, ext * 8 + 20000)
        pl.render()
        img = pl.screenshot(return_img=True)
        if lm:
            img = lm.draw(img, pl.renderer, cam[f], i, W, H, min(W, H) / 720)
        img = draw_hud(img, data, i, W, H, data["track_name"], credit, prof)
        proc.stdin.write(img.tobytes())
        if f % max(1, frames // 20) == 0:
            el = time.time() - t0
            print(f"   {f / frames * 100:5.1f}%  {f / max(el, 1e-3):.1f} 幀/s", end="\r")
    proc.stdin.close()
    proc.wait()
    pl.close()
    print(f"\n✅ 完成：{out}（{time.time() - t0:.0f} 秒）")
    return out


def main():
    ap = argparse.ArgumentParser(description="GPX → 3D 地形飛行影片（原型）")
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
    ap.add_argument("--shift", type=float, default=-0.12, help="畫面垂直偏移（-1~1）")
    ap.add_argument("--pitch", type=float, default=None, help="跟隨鏡頭高度比（越大越俯視；預設 0.85，衛星 1.0）")
    ap.add_argument("--cam-dist", type=float, default=None, help="跟隨鏡頭距離倍率（預設 1.0，衛星 2.2）")
    ap.add_argument("--line-width", type=float, default=7)
    ap.add_argument("--no-gpu", action="store_true")
    ap.add_argument("--landmarks", default=None, help="地標庫（.xlsx / .csv），預設使用程式旁的 locationGPS.xlsx")
    ap.add_argument("--radius", type=float, default=0.5, help="地標篩選半徑（公里）")
    ap.add_argument("--no-landmarks", action="store_true", help="不顯示地標")
    render(ap.parse_args())


if __name__ == "__main__":
    main()
