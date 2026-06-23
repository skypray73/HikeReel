#!/usr/bin/env python3
"""
gpx_to_video.py  v2 — 高速版
================================
將 GPX 軌跡輸出成影片：上方地圖動畫 + 下方同步高度圖（手機直式 9:16）

★ 效能優化：靜態底圖只用 matplotlib 畫一次，
   每幀改用 OpenCV + PIL 繪製動態內容，速度提升 30-50 倍。
★ 影片編碼：自動偵測 NVIDIA NVENC，透過 ffmpeg 管線 GPU 加速。

使用方式：
    python gpx_to_video.py your_track.gpx
    python gpx_to_video.py your_track.gpx --output my_video.mp4 --speed 15
    python gpx_to_video.py your_track.gpx --no-basemap --no-gpu
"""

import argparse, sys, os, math, time, warnings, shutil, subprocess

# ── PyInstaller 打包路徑修正 ─────────────────────────────────
# 讓 contextily / pyproj / rasterio 等套件能在 exe 內正確找到彼此
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    _mei = sys._MEIPASS
    # 把打包目錄加到最前面，確保 exe 內的套件優先被找到
    if _mei not in sys.path:
        sys.path.insert(0, _mei)
    # pyproj 需要額外的 PROJ 資料目錄
    import os as _os
    _proj_data = _os.path.join(_mei, 'pyproj', 'proj_dir', 'share', 'proj')
    if _os.path.isdir(_proj_data):
        _os.environ.setdefault('PROJ_DATA', _proj_data)
        _os.environ.setdefault('PROJ_LIB', _proj_data)
    # contextily 的 tile 快取目錄
    _cache = _os.path.join(_os.path.dirname(sys.executable), '.contextily_cache')
    _os.makedirs(_cache, exist_ok=True)
    _os.environ.setdefault('XDG_CACHE_HOME', _os.path.dirname(_cache))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.collections import LineCollection
import cv2
from PIL import Image, ImageDraw, ImageFont

warnings.filterwarnings("ignore")

# ── 中文字型設定 ──────────────────────────────────────────
PIL_FONT_BIG = None
PIL_FONT = None
PIL_FONT_SM = None

def setup_fonts():
    """找到中文字型，同時設定 matplotlib 和 PIL。"""
    global PIL_FONT_BIG, PIL_FONT, PIL_FONT_SM
    candidates = [
        "Microsoft JhengHei", "Microsoft YaHei", "MingLiU", "DFKai-SB",
        "PingFang TC", "Heiti TC", "WenQuanYi Micro Hei", "Noto Sans CJK TC",
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.family"] = name
            # 取得字型檔路徑給 PIL 用
            font_path = fm.findfont(fm.FontProperties(family=name))
            try:
                PIL_FONT_BIG = ImageFont.truetype(font_path, 32)   # 大數字
                PIL_FONT     = ImageFont.truetype(font_path, 22)   # 一般
                PIL_FONT_SM  = ImageFont.truetype(font_path, 16)   # 小字
            except Exception:
                PIL_FONT_BIG = ImageFont.load_default()
                PIL_FONT     = PIL_FONT_BIG
                PIL_FONT_SM  = PIL_FONT_BIG
            print(f"   字型：{name}")
            return
    print("   ⚠️  找不到中文字型")
    PIL_FONT_BIG = ImageFont.load_default()
    PIL_FONT     = ImageFont.load_default()
    PIL_FONT_SM  = ImageFont.load_default()

setup_fonts()
plt.rcParams["axes.unicode_minus"] = False

# 字型檔路徑（給動態縮放用）
_FONT_PATH = None
def _get_font_path():
    global _FONT_PATH
    if _FONT_PATH is not None:
        return _FONT_PATH
    candidates = [
        "Microsoft JhengHei", "Microsoft YaHei", "MingLiU", "DFKai-SB",
        "PingFang TC", "Heiti TC", "WenQuanYi Micro Hei", "Noto Sans CJK TC",
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    for name in candidates:
        if name in available:
            _FONT_PATH = fm.findfont(fm.FontProperties(family=name))
            return _FONT_PATH
    _FONT_PATH = ""
    return _FONT_PATH

def scale_fonts_for(width, height, is_landscape=False):
    """依影片解析度縮放 PIL 字型，讓數字在不同尺寸都清楚。"""
    global PIL_FONT_BIG, PIL_FONT, PIL_FONT_SM
    base = min(width, height)
    scale = base / 720.0
    # 橫式儀表板數字用較小字級（短邊是 1080 會太大）
    big_pt = 28 if is_landscape else 34
    fp = _get_font_path()
    fonts = [fp] if fp else []
    fonts += ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "arial.ttf"]
    for f in fonts:
        if not f:
            continue
        try:
            PIL_FONT_BIG = ImageFont.truetype(f, max(18, int(big_pt * scale)))
            PIL_FONT     = ImageFont.truetype(f, max(14, int(22 * scale)))
            PIL_FONT_SM  = ImageFont.truetype(f, max(11, int(15 * scale)))
            return
        except Exception:
            continue

# ── 套件檢查 ──────────────────────────────────────────────
try:
    import gpxpy
except ImportError:
    sys.exit("❌ 請先安裝 gpxpy：pip install gpxpy")

HAS_CTX = False
try:
    import contextily as ctx
    from pyproj import Transformer
    HAS_CTX = True
except ImportError:
    pass

# ── 工具函數 ──────────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def smooth(arr, w=7):
    if len(arr) <= w:
        return arr
    k = np.ones(w) / w
    p = w // 2
    return np.convolve(np.pad(arr, p, mode="edge"), k, mode="valid")[:len(arr)]

def slope_color_bgr(grade):
    """
    坡度（%）→ BGR 顏色（OpenCV 用 BGR 順序）
    上坡（grade > 0）→ 橘紅（B 小 G 小 R 大）
    下坡（grade < 0）→ 藍青（B 大 G 中 R 小）
    """
    MAX_GRADE = 15.0
    t = max(-1.0, min(1.0, grade / MAX_GRADE))
    MIN_T = 0.15   # 確保即使近乎平路也有明顯顏色

    if t >= 0:
        # 上坡：橘(R=255,G=160,B=80) → 深紅(R=255,G=20,B=0)
        s = MIN_T + t * (1.0 - MIN_T)
        R = 255
        G = int(160 - s * 140)        # 160 → 20
        B = int(max(0, 80 - s * 80))  # 80 → 0
    else:
        # 下坡：青(R=0,G=210,B=255) → 深藍(R=0,G=60,B=255)
        s = MIN_T + (-t) * (1.0 - MIN_T)
        R = 0
        G = int(210 - s * 150)        # 210 → 60
        B = 255

    return (B, G, R)  # OpenCV BGR 順序：上坡 R 大=紅，下坡 B 大=藍


def ele_color_bgr(ele, emin, emax):
    """舊介面相容（不再使用，以坡度版取代）"""
    return (200, 200, 200)

# ── 色彩常數（BGR for OpenCV） ─────────────────────────────
DARK_BG_RGB  = (26, 26, 46)
PANEL_BG_HEX = "#16213e"
ACCENT_BGR   = (96, 69, 233)    # #e94560
DONE_BGR     = (35, 166, 245)   # #f5a623
AHEAD_BGR    = (102, 68, 68)    # #444466
WHITE_BGR    = (255, 255, 255)
WP_COLOR_BGR = (102, 224, 255)  # #ffe066

DARK_BG_HEX  = "#1a1a2e"
TEXT_COL      = "#eaeaea"
GRID_COL      = "#2a2a4a"

# ── 地標總庫載入與篩選 ──────────────────────────────────
def load_landmarks(path, radius_km, lats, lon_arr):
    """
    從 .xlsx 或 .csv 地標總庫載入所有地標，
    只保留「距離 GPX 軌跡任一點在 radius_km 以內」的地標。

    檔案格式（第一列為欄位名稱）：
        名稱      | 緯度      | 經度       | 方向   | 備註（可省略）
        停車場     | 46.6131  | 12.2928   | below |
        Rifugio X | 46.6200  | 12.3100   | above |

    欄位名稱接受：名稱/name、緯度/lat、經度/lon/lng、方向/direction/dir
    方向欄可省略，缺少時程式自動計算。

    回傳：符合條件的 WAYPOINTS list
    """
    import os
    ext = os.path.splitext(path)[1].lower()

    # 讀取檔案
    rows = []
    if ext in (".xlsx", ".xls"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path, data_only=True)
            ws = wb.active
            all_rows = list(ws.iter_rows(values_only=True))
            if not all_rows:
                print("  ⚠️  地標庫是空的"); return []
            headers = [str(h).strip().lower() if h else "" for h in all_rows[0]]
            # 跳過第 2 列（說明列）：若第 2 列的緯度欄不是數字就跳過
            data_start = 1
            if len(all_rows) > 1:
                row2 = all_rows[1]
                try:
                    lat_idx = next((i for i, h in enumerate(headers)
                                    if h in ("緯度", "lat", "latitude")), None)
                    if lat_idx is not None and row2[lat_idx] is not None:
                        float(row2[lat_idx])   # 能轉 float 就是資料列
                    else:
                        data_start = 2         # 轉不了就跳過
                except (ValueError, TypeError):
                    data_start = 2             # 說明文字，跳過
            for row in all_rows[data_start:]:
                rows.append(dict(zip(headers, row)))
        except ImportError:
            print("  ⚠️  讀取 xlsx 需要 openpyxl：pip install openpyxl")
            return []
    elif ext == ".csv":
        import csv as csvmod
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csvmod.DictReader(f)
            reader.fieldnames = [k.strip().lower() for k in (reader.fieldnames or [])]
            for row in reader:
                rows.append({k.strip().lower(): v for k, v in row.items()})
    else:
        print(f"  ⚠️  不支援的地標庫格式：{ext}（請用 .xlsx 或 .csv）")
        return []

    # 欄位別名對應
    def get_col(row, *keys):
        for k in keys:
            if k in row and row[k] not in (None, ""):
                return row[k]
        return None

    # 軌跡邊界（加上 radius margin）
    deg_per_km = 1 / 111.0
    lat_min = lats.min()  - radius_km * deg_per_km
    lat_max = lats.max()  + radius_km * deg_per_km
    lon_min = lon_arr.min() - radius_km * deg_per_km
    lon_max = lon_arr.max() + radius_km * deg_per_km

    selected = []
    skipped  = []

    for row in rows:
        name = get_col(row, "名稱", "name", "地標", "landmark")
        lat  = get_col(row, "緯度", "lat", "latitude")
        lon  = get_col(row, "經度", "lon", "lng", "longitude")
        coord = get_col(row, "座標", "coord", "coordinates", "gps", "經緯度")
        dire = get_col(row, "方向", "direction", "dir") or "above"

        # 若有「座標」欄而沒有獨立的 lat/lon，從座標欄解析
        # 格式：「46.623, 12.308」或「46.623 12.308」或「46.623,12.308」
        if (lat is None or lon is None) and coord is not None:
            try:
                parts = str(coord).replace(",", " ").split()
                if len(parts) >= 2:
                    lat = float(parts[0])
                    lon = float(parts[1])
            except (ValueError, TypeError):
                pass

        if name is None or lat is None or lon is None:
            continue
        try:
            lat, lon = float(lat), float(lon)
        except (ValueError, TypeError):
            continue

        name = str(name).replace("\n", "\n")

        # 粗篩：邊界框
        if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
            skipped.append(str(name))
            continue

        # 精篩：實際最近距離
        min_dist = float("inf")
        for i in range(len(lats)):
            d = haversine(lats[i], lon_arr[i], lat, lon) / 1000
            if d < min_dist:
                min_dist = d
            if min_dist < radius_km:
                break  # 夠近了，不用繼續算

        if min_dist <= radius_km:
            selected.append((str(name), lat, lon, str(dire).strip().lower()))
        else:
            skipped.append(str(name))

    print(f"   📍 地標庫：共 {len(rows)} 筆，"
          f"篩選後顯示 {len(selected)} 個（半徑 {radius_km} km）")
    if skipped:
        print(f"      略過：{', '.join(skipped[:5])}"
              + (f" 等 {len(skipped)} 個" if len(skipped) > 5 else ""))
    return selected


# ── GPX 解析 ──────────────────────────────────────────────
def parse_gpx(path):
    with open(path, "r", encoding="utf-8") as f:
        gpx = gpxpy.parse(f)
    lats, lons, eles = [], [], []
    for trk in gpx.tracks:
        for seg in trk.segments:
            for pt in seg.points:
                lats.append(pt.latitude)
                lons.append(pt.longitude)
                eles.append(pt.elevation if pt.elevation else 0)
    if not lats:
        sys.exit("❌ GPX 中找不到軌跡點")
    lats = np.array(lats); lons = np.array(lons)
    eles = smooth(np.array(eles, dtype=float))
    dists = [0.0]
    for i in range(1, len(lats)):
        dists.append(dists[-1] + haversine(lats[i-1], lons[i-1], lats[i], lons[i]) / 1000)
    dists = np.array(dists)
    raw = (gpx.tracks[0].name or "").strip() if gpx.tracks else ""
    if not raw or raw.lower().startswith("new file"):
        raw = os.path.splitext(os.path.basename(path))[0]
    return dict(
        lats=lats, lons=lons, eles=eles, dists=dists,
        total_dist=dists[-1],
        ele_gain=float(np.sum(np.maximum(0, np.diff(eles)))),
        ele_loss=float(np.sum(np.maximum(0, -np.diff(eles)))),
        ele_max=float(eles.max()), ele_min=float(eles.min()),
        track_name=raw,
    )

# ── 底圖下載 ──────────────────────────────────────────────
def get_basemap(lats, lons, quality_boost=0):
    if not HAS_CTX:
        return None
    try:
        w, e = lons.min(), lons.max()
        s, n = lats.min(), lats.max()
        pl, pt = (e - w) * 0.15, (n - s) * 0.15
        W, S, E, N = w - pl, s - pt, e + pl, n + pt

        # ★ 關鍵：bounds2img 需要 Web Mercator (EPSG:3857) 座標
        to_3857 = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
        W_m, S_m = to_3857.transform(W, S)
        E_m, N_m = to_3857.transform(E, N)

        try:
            z_auto = int(ctx.tile._auto_zoom(W_m, S_m, E_m, N_m))
        except Exception:
            z_auto = 14

        # 依路線長度決定 zoom 上限：
        # 短路線（< 2km）→ zoom 最高 20，讓地圖更精細
        # 中等路線（2~10km）→ zoom 最高 18
        # 長路線（> 10km）→ zoom 最高 16
        track_len_km = ((lons.max()-lons.min())**2 + (lats.max()-lats.min())**2)**0.5 * 111
        if track_len_km < 2:
            max_zoom = 19
        elif track_len_km < 10:
            max_zoom = 18
        else:
            max_zoom = 16
        # quality_boost：高解析度時提高 zoom 上限，讓底圖更清晰
        # 0=720p, 1=1080p, 2=1440p, 3=4K
        max_zoom += quality_boost
        max_zoom = min(max_zoom, 20)   # OSM 最高 20
        z = min(z_auto + quality_boost, max_zoom)
        print(f"   zoom 級別：{z}（路線約 {track_len_km:.1f} km，品質+{quality_boost}）")

        img, ext = ctx.bounds2img(W_m, S_m, E_m, N_m, zoom=z,
                                  source=ctx.providers.OpenStreetMap.Mapnik)

        # ext 是 Web Mercator，轉回 WGS84 給 matplotlib 用
        to_4326 = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
        lo0, la0 = to_4326.transform(ext[0], ext[2])
        lo1, la1 = to_4326.transform(ext[1], ext[3])
        return img, (lo0, lo1, la0, la1)
    except Exception as ex:
        print(f"  ⚠️  底圖下載失敗（{ex}），改用純色背景")
        return None

# ══════════════════════════════════════════════════════════
# ★ 地標設定 ★
#
# 有兩種方式指定地標：
#
# 【方式 A】直接在下方清單填入（適合固定路線）
#   格式：("名稱", 緯度, 經度, "方向")
#   名稱中用 \n 可換行，例如 "山屋\nRifugio"
#   方向填 "above"/"below"/"left"/"right"（程式會自動修正避免蓋路線）
#   不要任何地標時把清單設為空：WAYPOINTS = []
#
# 【方式 B】執行時用 --waypoints 指定外部 CSV 檔（適合不同路線共用腳本）
#   CSV 格式（不需標題列）：名稱,緯度,經度,方向
#   範例：python gpx_to_video.py seceda.gpx --waypoints seceda_wp.csv
#   CSV 範例內容：
#     纜車站\nCable Car,46.5818,11.7601,right
#     Seceda峰頂,46.5888,11.7732,above
#
# --waypoints 指定後，下方 WAYPOINTS 清單會被忽略。
# ══════════════════════════════════════════════════════════
WAYPOINTS = [
    ("停車場",  46.61317190370517, 12.292823766377225, "below"),
    ("第一山屋\nRifugio Auronzo",  46.61232231546618, 12.295884144915448, "above"),
    ("第一二山屋間的教堂\nCappella degli Alpini", 46.6136036094214, 12.307327373186945, "above"),
    ("第二山屋\nRifugio Lavaredo", 46.61834222012101, 12.312010651332544, "above"),
    ("三尖峰側面\nForcella Lavaredo", 46.62312865780456, 12.31214867772597, "above"),
    ("第三山屋\nRifugio Locatelli", 46.63694396766085, 12.310484896696769, "above"),
    ("防空洞\nGrotta delle Tre Cime", 46.63824493282004, 12.309321367993546, "above"),
]

WP_MARKER_SIZE = 120
WP_FONT_SIZE   = 8

# ── 預渲染靜態背景（只跑一次） ─────────────────────────────
def render_static(data, width, height, basemap):
    """
    用 matplotlib 畫靜態底圖（底圖、全路線灰色線、地標、軸框、標題等），
    回傳：
      bg_img   — numpy (H, W, 3) uint8 RGB 背景圖
      map_px   — (N, 2) int32 每個 GPS 點在圖上的像素座標
      ele_px   — (N, 2) int32 每個高度點在圖上的像素座標
      ele_base — int 高度圖底部 y 像素
      ele_area — (top_y, bottom_y, left_x, right_x) 高度圖區域
      info_pos — (x, y) 統計資訊文字位置（像素）
    """
    lats, lons, eles, dists = data["lats"], data["lons"], data["eles"], data["dists"]
    emin, emax = data["ele_min"], data["ele_max"]
    n = len(lats)

    # 橫式判斷（提前，供字型縮放使用）
    is_landscape = width > height

    # 依解析度縮放 PIL 字型（橫式數字用較小字級）
    scale_fonts_for(width, height, is_landscape)

    dpi = width / 5.625
    fig_w, fig_h = width / dpi, height / dpi

    # ── 版面比例計算（橫式 / 直式）──────────────────────────

    if is_landscape:
        # ┌──────────┬──────────────┐
        # │ 標題      │              │
        # │ 距離      │              │
        # │ 海拔      │   地圖        │
        # │ 上坡      │  (右半填滿)   │
        # │ 下坡      │              │
        # │ 高度剖面   │              │
        # │ 浮水印    │              │
        # └──────────┴──────────────┘
        # 左欄寬 38%，右欄（地圖）填滿剩餘
        LEFT_W   = 0.38
        MAP_X    = 0.39
        MAP_W_FRAC = 0.60
        MAP_Y      = 0.03
        map_h_used = 0.94
        # ── 左欄佈局（figure fraction，由上到下）──
        L_TITLE_Y  = 0.950  # 標題
        # 儀表板 2×2：距離|海拔 一列，上坡|下坡 一列
        L_DASH_TOP = 0.890  # 第一列頂部（上移，讓下方有更多空間）
        L_DASH_ROW = 0.110  # 每列高度
        L_DASH_COL_W = (LEFT_W - 0.05) / 2   # 每格寬度（左欄平分兩格）
        L_DASH_X0  = 0.03                     # 左欄左邊界
        # 第二列底部 ≈ L_DASH_TOP - L_DASH_ROW*2 - L_DASH_ROW*0.85
        # ≈ 0.890 - 0.22 - 0.09 = 0.58
        # 高度剖面放在第二列下方，留間距
        # 浮水印在最底部 y=0.03 兩行約到 y=0.09
        # 高度剖面：Y底=0.10, 高=0.30 → 頂=0.40, X軸標籤到~0.07
        ELE_X, ELE_Y, ELE_W, ELE_H_ax = 0.11, 0.270, 0.25, 0.25
        ax_w_px_est = fig_w * dpi * MAP_W_FRAC
        ax_h_px_est = fig_h * dpi * map_h_used
        DASH_Y0 = L_DASH_TOP
        TITLE_Y = L_TITLE_Y
    else:
        # 直式（原本佈局）
        TITLE_H   = 0.055
        DASH_H    = 0.080
        ELE_H     = 0.215
        WMARK_H   = 0.075   # 加大浮水印區高度，讓距離(km)不貼著浮水印
        GAP       = 0.010
        MAP_H = 1.0 - TITLE_H - DASH_H - ELE_H - WMARK_H - GAP * 4
        MAP_H = max(MAP_H, 0.30)
        WMARK_Y = 0.0
        ELE_Y   = WMARK_Y + WMARK_H + GAP
        MAP_Y   = ELE_Y   + ELE_H   + GAP
        DASH_Y0 = MAP_Y   + MAP_H   + GAP
        TITLE_Y = DASH_Y0 + DASH_H  + GAP
        # YouTube Shorts 安全邊界：左右各內縮 6%
        SAFE = 0.06
        MAP_W_FRAC = 0.94 - SAFE * 2   # 寬度縮小 12%
        map_h_used = MAP_H
        ax_w_px_est = fig_w * dpi * MAP_W_FRAC
        ax_h_px_est = fig_h * dpi * MAP_H

    # 先算地圖比例，看地圖實際需要多少高度
    pad_lon = (lons.max() - lons.min()) * 0.12 + 0.002
    pad_lat = (lats.max() - lats.min()) * 0.12 + 0.002
    mid_lat = (lats.min() + lats.max()) / 2
    cos_lat = math.cos(math.radians(mid_lat))
    lon_center = (lons.min() + lons.max()) / 2
    lat_center = (lats.min() + lats.max()) / 2
    lon_range_needed = (lons.max() + pad_lon) - (lons.min() - pad_lon)
    lat_range_needed = (lats.max() + pad_lat) - (lats.min() - pad_lat)

    lat_from_lon = lon_range_needed * cos_lat * (ax_h_px_est / ax_w_px_est)
    lon_from_lat = lat_range_needed / cos_lat * (ax_w_px_est / ax_h_px_est)

    if lat_range_needed > lat_from_lon:
        lat_range = lat_range_needed
        lon_range = lon_from_lat
    else:
        lon_range = lon_range_needed
        lat_range = lat_from_lon
    # map_h_used 已在版面計算階段設定（橫式 0.92、直式 MAP_H），不覆寫

    # 建立 figure 和 axes（依橫式/直式）
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor=DARK_BG_HEX)
    if is_landscape:
        ax_map = fig.add_axes([MAP_X, MAP_Y, MAP_W_FRAC, map_h_used])
        ax_ele = fig.add_axes([ELE_X, ELE_Y, ELE_W, ELE_H_ax])
    else:
        ax_map = fig.add_axes([0.03 + SAFE, MAP_Y, MAP_W_FRAC, map_h_used])
        ax_ele = fig.add_axes([0.13 + SAFE, ELE_Y + 0.02, 0.82 - SAFE*2, ELE_H - 0.04])
    ax_map.set_facecolor(PANEL_BG_HEX)
    ax_ele.set_facecolor(PANEL_BG_HEX)

    # ── 精確取 axes 像素尺寸 ──
    fig.canvas.draw()
    ax_pos = ax_map.get_position()
    ax_w_px = fig_w * dpi * ax_pos.width
    ax_h_px = fig_h * dpi * ax_pos.height

    # 重新算一次（用精確像素尺寸）
    lat_from_lon = lon_range_needed * cos_lat * (ax_h_px / ax_w_px)
    lon_from_lat = lat_range_needed / cos_lat * (ax_w_px / ax_h_px)
    if lat_range_needed > lat_from_lon:
        lat_range = lat_range_needed
        lon_range = lon_from_lat
    else:
        lon_range = lon_range_needed
        lat_range = lat_from_lon

    lat_lo = lat_center - lat_range / 2
    lat_hi = lat_center + lat_range / 2
    lon_lo = lon_center - lon_range / 2
    lon_hi = lon_center + lon_range / 2

    ax_map.set_xlim(lon_lo, lon_hi)
    ax_map.set_ylim(lat_lo, lat_hi)

    if basemap is not None:
        img, (lo0, lo1, la0, la1) = basemap
        ax_map.imshow(img, extent=[lo0, lo1, la0, la1],
                      aspect="auto", origin="upper", alpha=0.95)

    # 全路線灰色底線
    ax_map.plot(lons, lats, color="#444466", lw=2.5, alpha=0.5, zorder=2)

    # 起終點
    ax_map.scatter(lons[0],  lats[0],  s=80, marker="^", color="#00e676", zorder=5)
    ax_map.scatter(lons[-1], lats[-1], s=80, marker="s", color="#ff5252", zorder=5)

    # ── 地標標記與標籤 ──────────────────────────────────────
    from matplotlib.lines import Line2D as MLine2D

    xlim = ax_map.get_xlim()
    ylim = ax_map.get_ylim()
    xspan = xlim[1] - xlim[0]
    yspan = ylim[1] - ylim[0]
    ax_pos = ax_map.get_position()
    ax_w_px = fig_w * dpi * ax_pos.width
    ax_h_px = fig_h * dpi * ax_pos.height

    def data_to_ax(lon, lat):
        """地理座標 → axes fraction（x 從左到右，y 從下到上）"""
        return (lon - xlim[0]) / xspan, (lat - ylim[0]) / yspan

    # 路線轉 axes fraction
    _track_raw = np.array([data_to_ax(lons[i], lats[i]) for i in range(len(lats))])
    # 內插加密：相鄰點之間補點，避免線段穿過標籤框卻偵測不到
    _dense = [_track_raw[0]]
    for i in range(1, len(_track_raw)):
        p0, p1 = _track_raw[i-1], _track_raw[i]
        seg = math.hypot(p1[0]-p0[0], p1[1]-p0[1])
        steps = max(1, int(seg / 0.008))   # 每 0.008 fraction 補一點
        for s in range(1, steps+1):
            t = s / steps
            _dense.append((p0[0]+(p1[0]-p0[0])*t, p0[1]+(p1[1]-p0[1])*t))
    track_ax = np.array(_dense)

    def box_crosses_track(box, pad=0.012):
        """標籤框是否與路線重疊（含 padding，加密後的點）"""
        x0, y0, x1, y1 = box[0]-pad, box[1]-pad, box[2]+pad, box[3]+pad
        in_x = (track_ax[:, 0] >= x0) & (track_ax[:, 0] <= x1)
        if not in_x.any():
            return False
        return ((track_ax[in_x, 1] >= y0) & (track_ax[in_x, 1] <= y1)).any()

    def overlaps_box(b1, b2, pad=0.012):
        return not (b1[2]+pad < b2[0] or b2[2]+pad < b1[0] or
                    b1[3]+pad < b2[1] or b2[3]+pad < b1[1])

    # 地標字級：依短邊像素縮放，讓各解析度視覺比例一致
    # 目標：標籤字身高約佔畫面短邊的 1.6%（720→約11.5px, 1080→約17px）
    short_side = min(width, height)
    target_char_px = short_side * 0.016
    if is_landscape:
        target_char_px *= 0.92   # 橫式地圖較大，字可略小
    # matplotlib fontsize(point) = 像素 * 72 / dpi
    wp_fs = target_char_px * 72.0 / dpi
    _char_h_px = target_char_px
    _char_w_px = _char_h_px * 1.05

    def estimate_size(name):
        lines = name.split("\n")
        ch_count = max(len(l) for l in lines)
        # 估算 bbox 寬高（含 boxstyle pad≈0.3 字高 的內距 + 粗體加成）
        text_w = ch_count * _char_w_px
        text_h = len(lines) * _char_h_px * 1.25   # 行距
        pad = _char_h_px * 0.6                      # 上下左右 padding
        w_px = text_w + pad * 2
        h_px = text_h + pad * 2
        # 額外放大 15% 安全邊界，避免低估造成重疊
        return (w_px * 1.15) / ax_w_px, (h_px * 1.15) / ax_h_px

    # 左上儀表板佔用區（axes fraction，y 從下往上）
    INFO_BOX = (0.0, 0.95, 1.0, 1.02)   # 幾乎不佔地圖空間（儀表板已在地圖外）

    MARGIN = 0.01
    placed = []  # 已放標籤的 bbox list

    # marker 大小依「地圖 axes 短邊像素」縮放（橫式/直式視覺一致）
    # ax_w_px, ax_h_px 是地圖 axes 的實際像素尺寸
    _map_short = min(ax_w_px, ax_h_px)
    _marker_base = 0.016 if not is_landscape else 0.011  # 整體縮小約一半
    _marker_s = (_map_short * _marker_base) ** 2 / 6
    for name, lat, lon, lp in WAYPOINTS:
        ax_map.scatter(lon, lat, s=_marker_s, marker="D",
                       color="#ffe066", edgecolors=DARK_BG_HEX,
                       linewidths=1.0, zorder=8)

        ax_x, ax_y = data_to_ax(lon, lat)
        lw, lh = estimate_size(name)

        # 候選位置：4 個主方向 × 3 個距離 = 12 個
        # 加入 4 個斜角 × 3 個距離 = 12 個
        # 共 24 個候選，依照順序嘗試（優先水平/垂直方向）
        OFFSETS = []
        for dist in [0.09, 0.13, 0.17, 0.22, 0.28]:   # 更多距離層級
            for ddx, ddy in [
                (1, 0), (-1, 0), (0, 1), (0, -1),       # 右、左、上、下
                (0.7, 0.7), (-0.7, 0.7),                  # 右上、左上
                (0.7, -0.7), (-0.7, -0.7),                # 右下、左下
            ]:
                OFFSETS.append((ddx * dist, ddy * dist))

        best_box = None
        best_score = 1e9
        best_pos = (ax_x + 0.15, ax_y)  # fallback

        for odx, ody in OFFSETS:
            # 標籤放置點（標籤框的 bottom-left 或 bottom-right 等）
            # 統一用「標籤框中心」來計算偏移，再推算左下角
            cx_label = ax_x + odx
            cy_label = ax_y + ody
            # 標籤框（以中心為基準）
            bx0 = cx_label - lw / 2
            bx1 = cx_label + lw / 2
            by0 = cy_label - lh / 2
            by1 = cy_label + lh / 2

            # 邊界夾取（確保標籤框完整在畫面內）
            if bx0 < MARGIN:
                bx0, bx1 = MARGIN, MARGIN + lw
            if bx1 > 1 - MARGIN:
                bx0, bx1 = 1 - MARGIN - lw, 1 - MARGIN
            if by0 < MARGIN:
                by0, by1 = MARGIN, MARGIN + lh
            if by1 > 1 - MARGIN:
                by0, by1 = 1 - MARGIN - lh, 1 - MARGIN

            box = (bx0, by0, bx1, by1)

            # 評分（懲罰加重，標籤重疊和壓線都要強力避免）
            score = 0
            if box_crosses_track(box):
                score += 5000          # 壓到路線：嚴重扣分
            for pb in placed:
                if overlaps_box(box, pb):
                    score += 3000      # 標籤互相重疊：嚴重扣分
            if overlaps_box(box, INFO_BOX):
                score += 500
            # 偏好離地標近的（次要因素，權重低）
            score += math.sqrt(odx**2 + ody**2) * 8

            if score < best_score:
                best_score = score
                best_box = box
                best_pos = (cx_label, cy_label)

        placed.append(best_box)
        bx0, by0, bx1, by1 = best_box
        cx_label, cy_label = best_pos

        # 畫標籤（wp_fs 已在上方統一計算）
        ax_map.text(
            cx_label, cy_label, name,
            transform=ax_map.transAxes,
            ha="center", va="center",
            fontsize=wp_fs, fontweight="bold",
            color="#ffe066", zorder=9,
            bbox=dict(boxstyle="round,pad=0.3", fc=DARK_BG_HEX,
                      alpha=0.88, ec="#ffe066", linewidth=0.8),
        )

        # 黑色粗虛線指引線（標記點 → 標籤框中心）
        line = MLine2D(
            [ax_x, cx_label], [ax_y, cy_label],
            transform=ax_map.transAxes,
            color="black",
            linewidth=2.5,
            linestyle=(0, (2, 2)),
            alpha=0.85,
            zorder=6,
        )
        ax_map.add_line(line)
        # 黃色細線疊在黑線上，形成黑邊效果讓虛線更醒目
        line2 = MLine2D(
            [ax_x, cx_label], [ax_y, cy_label],
            transform=ax_map.transAxes,
            color="#ffe066",
            linewidth=1.0,
            linestyle=(0, (2, 2)),
            alpha=0.9,
            zorder=6,
        )
        ax_map.add_line(line2)

    ax_map.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
    for sp in ax_map.spines.values():
        sp.set_edgecolor(GRID_COL)

    DASH_LABELS = ["距離", "海拔", "↑上坡", "↓下坡"]
    DASH_COLORS = ["#ffc864", "#82c8ff", "#ff8264", "#82dcc8"]

    if is_landscape:
        # 橫式：標題自動縮放，不超過左欄寬度（中線）
        title_txt = data["track_name"]
        max_title_w = (LEFT_W - 0.04) * width   # 像素寬度上限
        fig.canvas.draw()
        rend = fig.canvas.get_renderer()
        # 先找出合適字級（只測量，不殘留）
        title_fs = 26
        while title_fs > 8:
            tmp = fig.text(0.04, L_TITLE_Y, title_txt, ha="left", va="center",
                           fontsize=title_fs, fontweight="bold",
                           transform=fig.transFigure)
            w_px_title = tmp.get_window_extent(rend).width
            tmp.remove()
            if w_px_title <= max_title_w:
                break
            title_fs -= 1
        # 確定字級後，正式畫一次標題（保證存在）
        fig.text(0.04, L_TITLE_Y, title_txt, ha="left", va="center",
                 color=TEXT_COL, fontsize=title_fs, fontweight="bold",
                 transform=fig.transFigure, zorder=12)
        # 儀表板 2×2：距離|海拔（第一列）、上坡|下坡（第二列）
        # i=0 距離(左) i=1 海拔(右) i=2 上坡(左) i=3 下坡(右)
        for i, (lbl, col) in enumerate(zip(DASH_LABELS, DASH_COLORS)):
            row = i // 2          # 0 或 1
            col_i = i % 2         # 0(左) 或 1(右)
            cell_x = L_DASH_X0 + col_i * (L_DASH_COL_W + 0.01)
            cell_y = L_DASH_TOP - row * L_DASH_ROW
            rect = plt.Rectangle((cell_x, cell_y - L_DASH_ROW*0.85),
                                  L_DASH_COL_W, L_DASH_ROW*0.8,
                                  transform=fig.transFigure, figure=fig,
                                  fc="#0f1932", alpha=0.88, zorder=10)
            fig.add_artist(rect)
            bar = plt.Rectangle((cell_x, cell_y - L_DASH_ROW*0.85),
                                 0.005, L_DASH_ROW*0.8,
                                 transform=fig.transFigure, figure=fig,
                                 fc=col, zorder=11)
            fig.add_artist(bar)
            # 標籤放格子頂部（小字，橫式用較小字級避免擠壓數字）
            fig.text(cell_x + 0.014, cell_y - L_DASH_ROW*0.06,
                     lbl, fontsize=10, color="#c8c8e0",
                     transform=fig.transFigure, va="top", zorder=12)
    else:
        # 直式：標題在上，儀表板 4 格橫排
        fig.text(0.50, TITLE_Y + TITLE_H * 0.5, data["track_name"],
                 ha="center", va="top",
                 color=TEXT_COL, fontsize=22, fontweight="bold",
                 transform=fig.transFigure, zorder=12)
        # 儀表板 4 格內縮安全邊界
        dash_total_w = 0.96 - SAFE * 2      # 4 格總寬度
        cell_step = dash_total_w / 4         # 每格含間隙
        cell_w = cell_step - 0.02            # 每格實際寬度
        dash_left = 0.03 + SAFE
        for i, (lbl, col) in enumerate(zip(DASH_LABELS, DASH_COLORS)):
            x0 = dash_left + i * cell_step
            w  = cell_w
            rect = plt.Rectangle((x0, DASH_Y0), w, DASH_H,
                                  transform=fig.transFigure, figure=fig,
                                  fc="#0f1932", alpha=0.88, zorder=10)
            fig.add_artist(rect)
            bar = plt.Rectangle((x0, DASH_Y0), 0.006, DASH_H,
                                 transform=fig.transFigure, figure=fig,
                                 fc=col, zorder=11)
            fig.add_artist(bar)
            fig.text(x0 + 0.012, DASH_Y0 + DASH_H * 0.92,
                     lbl, fontsize=12, color="#c8c8e0",
                     transform=fig.transFigure, va="top", zorder=12)

    # ── 高度圖靜態內容 ──
    ax_ele.fill_between(dists, eles, emin - 20, color="#444466", alpha=0.35)
    ax_ele.plot(dists, eles, color="#444466", lw=1.5)
    y_pad = (emax - emin) * 0.12 + 20
    ax_ele.set_xlim(0, data["total_dist"])
    ax_ele.set_ylim(emin - y_pad, emax + y_pad)
    _ele_fs = 9 if is_landscape else 12
    ax_ele.set_xlabel("距離 (km)", color=TEXT_COL, fontsize=_ele_fs, labelpad=2)
    ax_ele.set_ylabel("海拔 (m)", color=TEXT_COL, fontsize=_ele_fs, labelpad=2)
    ax_ele.set_title("高度剖面", color=TEXT_COL,
                     fontsize=(11 if is_landscape else 14),
                     fontweight="bold", pad=3)
    ax_ele.tick_params(colors=TEXT_COL, labelsize=(8 if is_landscape else 10))
    for sp in ax_ele.spines.values():
        sp.set_edgecolor(GRID_COL)
    ax_ele.yaxis.set_tick_params(labelcolor=TEXT_COL)
    ax_ele.xaxis.set_tick_params(labelcolor=TEXT_COL)

    # ── 高度水平虛線（間隔依高度範圍自動調整，避免過密）──
    import matplotlib.ticker as mticker
    import math as _m
    y_lo, y_hi = ax_ele.get_ylim()
    ele_span = y_hi - y_lo
    # 目標：約 4~7 條虛線。範圍小用小間隔，範圍大用大間隔
    for step in [10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000]:
        if ele_span / step <= 7:
            break
    ax_ele.yaxis.set_major_locator(mticker.MultipleLocator(step))
    first = _m.ceil(y_lo / step) * step
    yv = first
    while yv <= y_hi:
        ax_ele.axhline(yv, color="#8888aa", lw=0.8, alpha=0.45,
                       linestyle=(0, (4, 3)), zorder=1)
        yv += step
    # X 軸格線保留（淡）
    ax_ele.grid(True, axis="x", color=GRID_COL, lw=0.5, alpha=0.4)

    # 浮水印（橫式分兩行，避免超出中線）
    if is_landscape:
        fig.text(0.02, 0.015,
                 "HikeReel｜開發：Skypray Huang\n首版日期：2026/6/21",
                 ha="left", va="bottom", fontsize=9, color="#aaaab8",
                 linespacing=1.4,
                 transform=fig.transFigure, zorder=10)
    else:
        fig.text(0.50, 0.008,
                 "HikeReel　開發：Skypray Huang　首版日期：2026/6/21",
                 ha="center", va="bottom", fontsize=11, color="#aaaab8",
                 transform=fig.transFigure, zorder=10)

    # ── 渲染並擷取 ──
    fig.canvas.draw()
    h_px = int(fig.get_figheight() * dpi)
    w_px = int(fig.get_figwidth()  * dpi)
    buf = fig.canvas.buffer_rgba()
    # buffer_rgba() 是 RGBA，轉成 BGR 讓後續 cv2 操作顏色正確
    rgba = np.frombuffer(buf, dtype=np.uint8).reshape(h_px, w_px, 4)
    bg = rgba[:, :, [2, 1, 0]].copy()   # RGBA → BGR（R↔B 對調，去掉 A）

    # ── 座標轉換：資料座標 → 像素座標 ──
    map_px = np.zeros((n, 2), dtype=np.int32)
    ele_px = np.zeros((n, 2), dtype=np.int32)
    for i in range(n):
        xy = ax_map.transData.transform((lons[i], lats[i]))
        map_px[i] = (int(round(xy[0])), h_px - int(round(xy[1])))
        xy2 = ax_ele.transData.transform((dists[i], eles[i]))
        ele_px[i] = (int(round(xy2[0])), h_px - int(round(xy2[1])))

    # 高度圖底線 y
    base_xy = ax_ele.transData.transform((0, emin - 20))
    ele_base_y = h_px - int(round(base_xy[1]))

    # 高度圖區域邊界（用來畫垂直線）
    ele_bbox = ax_ele.get_window_extent(fig.canvas.get_renderer())
    ele_area = (
        h_px - int(round(ele_bbox.y1)),  # top_y
        h_px - int(round(ele_bbox.y0)),  # bottom_y
        int(round(ele_bbox.x0)),          # left_x
        int(round(ele_bbox.x1)),          # right_x
    )

    # 儀表板每格的數字位置（圖片像素座標，左上角）
    # dash_cells = [(x_px, y_px), ...] 共 4 個
    dash_cells = []
    if is_landscape:
        # 2×2 佈局：i=0 距離(左上) i=1 海拔(右上) i=2 上坡(左下) i=3 下坡(右下)
        for i in range(4):
            row = i // 2
            col_i = i % 2
            cell_x = L_DASH_X0 + col_i * (L_DASH_COL_W + 0.01)
            cell_y = L_DASH_TOP - row * L_DASH_ROW
            x_px = int((cell_x + 0.014) * w_px)
            # 數字放格子 40% 處，讓海拔小字有空間放在格子 70% 不超出
            y_px = int((1 - (cell_y - L_DASH_ROW*0.40)) * h_px)
            dash_cells.append((x_px, y_px))
    else:
        dash_top_y = int((1 - DASH_Y0 - DASH_H) * h_px)
        # 與儀表板格子一致的內縮計算（SAFE 安全邊界）
        _safe = 0.06
        _dash_total_w = 0.96 - _safe * 2
        _cell_step = _dash_total_w / 4
        _dash_left = 0.03 + _safe
        for i in range(4):
            x_px = int((_dash_left + i * _cell_step + 0.012) * w_px)
            y_px = dash_top_y + int(DASH_H * h_px * 0.30)
            dash_cells.append((x_px, y_px))

    plt.close(fig)

    return (bg, map_px, ele_px, ele_base_y, ele_area,
            dash_cells, is_landscape, w_px)


# ── 逐幀快速渲染（OpenCV + PIL） ──────────────────────────
def render_frame(bg, map_px, ele_px, ele_base_y, ele_area,
                 dash_cells, is_landscape, frame_w,
                 data, pos, seg_colors):
    """
    基於預渲染背景，用 OpenCV 畫動態內容：
    - 已走彩色軌跡（map）
    - 目前位置 dot（map）
    - 已走高度填色（ele）
    - 目前位置垂直線 + dot（ele）
    - 統計文字（PIL）
    """
    frame = bg.copy()  # ~1ms for 720x1280
    eles  = data["eles"]
    n = len(eles)

    # ── 地圖：已走彩色軌跡 ──
    if pos >= 2:
        for i in range(pos - 1):
            cv2.line(frame,
                     tuple(map_px[i]), tuple(map_px[i + 1]),
                     seg_colors[i], 5, cv2.LINE_AA)

    # 目前位置 dot
    cx, cy = int(map_px[pos][0]), int(map_px[pos][1])
    cv2.circle(frame, (cx, cy), 10, WHITE_BGR, -1, cv2.LINE_AA)
    cv2.circle(frame, (cx, cy), 6,  ACCENT_BGR, -1, cv2.LINE_AA)

    # ── 高度圖：已走填色 ──
    if pos >= 1:
        pts = [(int(ele_px[0][0]), ele_base_y)]
        for i in range(pos + 1):
            pts.append((int(ele_px[i][0]), int(ele_px[i][1])))
        pts.append((int(ele_px[pos][0]), ele_base_y))
        overlay = frame.copy()
        cv2.fillPoly(overlay, [np.array(pts, dtype=np.int32)], DONE_BGR)
        cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
        # 已走線
        for i in range(pos):
            cv2.line(frame, tuple(ele_px[i]), tuple(ele_px[i+1]),
                     DONE_BGR, 3, cv2.LINE_AA)

    # 垂直線
    ex, ey = int(ele_px[pos][0]), int(ele_px[pos][1])
    top_y, bot_y = ele_area[0], ele_area[1]
    cv2.line(frame, (ex, top_y), (ex, bot_y), ACCENT_BGR, 2, cv2.LINE_AA)

    # dot on elevation
    cv2.circle(frame, (ex, ey), 7, WHITE_BGR, -1, cv2.LINE_AA)
    cv2.circle(frame, (ex, ey), 4, ACCENT_BGR, -1, cv2.LINE_AA)

    # ── 動態儀表板列（標題正下方，4 格橫排）──
    pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)

    # 動態值
    cur_dist = data['dists'][pos]
    cur_ele  = eles[pos]
    cur_gain = float(np.sum(np.maximum(0,  np.diff(eles[:pos+1])))) if pos > 0 else 0.0
    cur_loss = float(np.sum(np.maximum(0, -np.diff(eles[:pos+1])))) if pos > 0 else 0.0

    total_gain = data.get('ele_gain', 0)
    total_loss = data.get('ele_loss', 0)
    ele_max    = data.get('ele_max', cur_ele)
    ele_min    = data.get('ele_min', cur_ele)

    # (大數字, 單位文字, 顏色, 副文字, 副文字顏色)
    items = [
        (f"{cur_dist:.2f}",  f"/ {data['total_dist']:.1f} km", (255, 200, 100),
         None, None),
        (f"{cur_ele:.0f}",   "m",                               (130, 200, 255),
         f"▲{ele_max:.0f}  ▼{ele_min:.0f} m",                  (140, 170, 210)),
        (f"{cur_gain:.0f}",  f"/ {total_gain:.0f} m",          (255, 130, 100),
         None, None),
        (f"{cur_loss:.0f}",  f"/ {total_loss:.0f} m",          (130, 220, 200),
         None, None),
    ]

    # 每格用 dash_cells 提供的 (x, y) 位置畫數字+單位+副文字
    for i, (big, unit, color, sub, sub_col) in enumerate(items):
        cx, cy = dash_cells[i]
        draw.text((cx, cy), big, font=PIL_FONT_BIG, fill=color)
        big_w = draw.textlength(big, font=PIL_FONT_BIG)
        draw.text((cx + big_w + 5, cy + 10), unit,
                  font=PIL_FONT_SM, fill=(180, 180, 200))
        # 副文字（海拔最高最低，放在數字下方小字）
        if sub:
            # 算出格子底部像素位置（不超出格子）
            sub_y = cy + int(PIL_FONT_BIG.size * 1.1)
            draw.text((cx, sub_y), sub, font=PIL_FONT_SM, fill=sub_col)

    # 當前高度標籤（在高度圖 dot 旁）
    ele_label = f"{eles[pos]:.0f} m"
    lx = ex + 10 if ex + 80 < frame.shape[1] else ex - 80
    draw.text((lx, ey - 10), ele_label, font=PIL_FONT_SM, fill=(234, 234, 234))

    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


# ── NVENC 偵測 ────────────────────────────────────────────
def find_ffmpeg():
    """
    尋找 ffmpeg.exe，優先順序：
    1. 程式（exe）同資料夾的 ffmpeg.exe / ffmpeg/bin/ffmpeg.exe
    2. PyInstaller 打包進去的暫存資料夾（sys._MEIPASS）
    3. 系統 PATH 裡的 ffmpeg
    回傳 ffmpeg 路徑，找不到回傳 None
    """
    import sys as _sys
    candidates = []

    # 1. exe 同資料夾
    if getattr(_sys, 'frozen', False):
        base = os.path.dirname(_sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(base, "ffmpeg.exe"))
    candidates.append(os.path.join(base, "ffmpeg", "bin", "ffmpeg.exe"))
    candidates.append(os.path.join(base, "ffmpeg", "ffmpeg.exe"))

    # 2. PyInstaller 暫存資料夾
    if hasattr(_sys, "_MEIPASS"):
        candidates.append(os.path.join(_sys._MEIPASS, "ffmpeg.exe"))

    for p in candidates:
        if os.path.isfile(p):
            return p

    # 3. 系統 PATH
    return shutil.which("ffmpeg")


def detect_encoder():
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None, None
    try:
        r = subprocess.run(
            [ffmpeg, "-hide_banner", "-f", "lavfi", "-i",
             "nullsrc=s=64x64:d=0.1", "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, timeout=10)
        if r.returncode == 0:
            return "h264_nvenc", "NVIDIA GPU"
    except Exception:
        pass
    return "libx264", "CPU"


# ── 主流程 ────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="GPX → 軌跡動畫影片 v2（高速版）")
    parser.add_argument("gpx", help="GPX 檔案路徑")
    parser.add_argument("--title",      default=None,
                        help="影片標題（預設用 GPX 主檔名）")
    parser.add_argument("--output",     default=None,
                        help="輸出檔名（預設與 GPX 同名，副檔名改 .mp4）")
    parser.add_argument("--fps",        type=int,   default=24)
    parser.add_argument("--speed",      type=float, default=2)
    parser.add_argument("--width",      type=int,   default=720)
    parser.add_argument("--height",     type=int,   default=1280)
    parser.add_argument("--no-basemap", action="store_true")
    parser.add_argument("--no-gpu",     action="store_true")
    parser.add_argument("--landmarks",  default=None,
                        help="地標總庫檔案路徑（.xlsx 或 .csv），自動篩選軌跡附近的地標")
    parser.add_argument("--radius",     type=float, default=0.5,
                        help="地標篩選半徑（公里，預設 0.5 km）")
    args = parser.parse_args()

    args.width  += args.width  % 2  # ffmpeg 需要偶數
    args.height += args.height % 2

    # 輸出檔名預設：與 GPX 同主檔名 + 解析度後綴
    if args.output is None:
        base = os.path.splitext(os.path.basename(args.gpx))[0]
        args.output = f"{base} ({args.width}x{args.height}).mp4"

    print(f"\n🗺️  GPX 軌跡影片產生器 v2（高速版）")
    print(f"{'─'*44}")

    # 編碼器
    if args.no_gpu:
        enc, hw = "libx264", "CPU（手動）"
    else:
        enc, hw = detect_encoder()
    if enc is None:
        print("   ⚠️  未偵測到 ffmpeg，改用 OpenCV 編碼")
        use_ff = False
    else:
        print(f"   編碼器：{enc}（{hw}）")
        use_ff = True
        if "GPU" in (hw or ""):
            print("   🚀 NVIDIA NVENC 加速已啟用！")

    # 解析 GPX
    print(f"\n📂 讀取 {args.gpx} ...")
    data = parse_gpx(args.gpx)
    n = len(data["lats"])
    # --title 優先，其次 GPX 內名稱，再其次主檔名（parse_gpx 已處理後兩者）
    if args.title:
        data["track_name"] = args.title
    print(f"   軌跡名稱：{data['track_name']}")

    # ── 地標總庫：載入並篩選（需在解析 GPX 之後才有座標可用）──
    global WAYPOINTS
    if args.landmarks:
        WAYPOINTS = load_landmarks(args.landmarks, args.radius,
                                   data["lats"], data["lons"])
    print(f"   軌跡點數：{n}")
    print(f"   總距離：  {data['total_dist']:.2f} km")
    print(f"   海拔範圍：{data['ele_min']:.0f} ~ {data['ele_max']:.0f} m")
    print(f"   總爬升：  {data['ele_gain']:.0f} m")

    # 底圖
    basemap = None
    if not args.no_basemap and HAS_CTX:
        print("\n🌐 下載衛星底圖...")
        basemap = get_basemap(data["lats"], data["lons"])
        if basemap:
            print("   底圖下載完成 ✓")
    elif not HAS_CTX and not args.no_basemap:
        print("\n⚠️  未安裝 contextily，改用純色背景")

    # ── 預渲染靜態背景（只跑一次！）──
    print("\n🎨 預渲染靜態底圖...")
    t0 = time.time()
    bg, map_px, ele_px, ele_base_y, ele_area, dash_cells, is_landscape, frame_w = \
        render_static(data, args.width, args.height, basemap)
    print(f"   完成（{time.time()-t0:.1f} 秒）")

    # 確保背景尺寸正確
    if bg.shape[1] != args.width or bg.shape[0] != args.height:
        bg = cv2.resize(bg, (args.width, args.height))
        # 重新計算需要按比例調整座標，簡單起見直接 resize 背景
        # 座標已對應原始 figure pixel，若 resize 了就不對
        # 所以改成讓 figure 直接產出正確尺寸
        pass

    # 預算顏色
    # 計算每段坡度（%），用於上色
    eles_arr = data["eles"]
    dists_arr = data["dists"]
    seg_colors = []
    for i in range(n):
        if i == 0 or i == n - 1:
            seg_colors.append(slope_color_bgr(0))
        else:
            # 用前後各 3 點平均坡度，減少雜訊
            i0 = max(0, i - 3)
            i1 = min(n - 1, i + 3)
            d_ele  = float(eles_arr[i1] - eles_arr[i0])
            d_dist = (float(dists_arr[i1] - dists_arr[i0]) * 1000) + 1e-3  # km→m
            grade  = (d_ele / d_dist) * 100  # 坡度 %
            seg_colors.append(slope_color_bgr(grade))

    # 幀數
    total_frames = max(60, int(n * args.fps / args.speed))
    duration = total_frames / args.fps
    print(f"\n🎬 影片設定")
    print(f"   解析度：{args.width} × {args.height}")
    print(f"   幀率：  {args.fps} fps  ×  {args.speed}x 加速")
    print(f"   總幀數：{total_frames}（約 {duration:.1f} 秒影片）")
    print(f"   輸出：  {args.output}")

    # ── 開啟 ffmpeg / OpenCV 輸出 ──
    ff_proc, cv_out = None, None
    if use_ff:
        cmd = [find_ffmpeg(), "-y",
               "-f", "rawvideo", "-vcodec", "rawvideo",
               "-pix_fmt", "rgb24",
               "-s", f"{args.width}x{args.height}",
               "-r", str(args.fps), "-i", "-",
               "-c:v", enc]
        if enc == "h264_nvenc":
            cmd += ["-preset", "p4", "-rc", "vbr", "-cq", "28", "-b:v", "0"]
        else:
            cmd += ["-preset", "veryfast", "-crf", "26"]
        cmd += ["-pix_fmt", "yuv420p", args.output]
        ff_proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        cv_out = cv2.VideoWriter(args.output, fourcc, args.fps,
                                 (args.width, args.height))

    # ── 逐幀渲染 ──
    print(f"\n⏳ 渲染中...")
    t_start = time.time()

    for i in range(total_frames):
        pos = max(1, int(round(i / total_frames * (n - 1))))

        frame = render_frame(bg, map_px, ele_px, ele_base_y, ele_area,
                             dash_cells, is_landscape, frame_w,
                             data, pos, seg_colors)

        # 確保尺寸
        if frame.shape[1] != args.width or frame.shape[0] != args.height:
            frame = cv2.resize(frame, (args.width, args.height))

        if ff_proc:
            # ffmpeg pipe 需要 RGB，frame 是 BGR，轉換後送出
            ff_proc.stdin.write(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).tobytes())
        else:
            cv_out.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

        # 進度
        if i % max(1, total_frames // 20) == 0:
            pct = i / total_frames * 100
            elapsed = time.time() - t_start
            eta = (elapsed / max(i, 1)) * (total_frames - i)
            bar = "█" * int(pct // 5) + "░" * (20 - int(pct // 5))
            fps_now = i / elapsed if elapsed > 0.1 else 0
            print(f"   [{bar}] {pct:5.1f}%  {fps_now:.0f} 幀/s  剩餘 {eta:.0f}s  ", end="\r")

    # 關閉
    if ff_proc:
        ff_proc.stdin.close()
        ff_proc.wait()
    if cv_out:
        cv_out.release()

    elapsed = time.time() - t_start
    print(f"\n   [{'█'*20}] 100.0%  完成！")
    print(f"\n✅ 影片已輸出：{args.output}")
    print(f"   總耗時：{elapsed:.1f} 秒（{total_frames/elapsed:.1f} 幀/秒）")
    if use_ff:
        print(f"   編碼：{enc}（{hw}）")
    print()


if __name__ == "__main__":
    main()
