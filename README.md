# HikeReel v1.00

**HikeReel** 是一個將 GPX 健行軌跡轉換成動態影片的工具，適合上傳至 YouTube Shorts 或 Instagram Reels。

## ⬇️ 下載執行檔（Windows）

> 不需要安裝 Python，下載即用。

**[➡️ 前往下載頁面（Releases）](https://github.com/skypray73/HikeReel/releases/latest)**

下載內容：
- `HikeReel.exe` — 主程式（Windows 64位元）
- `locationGPS.xlsx` — 地標資料庫範本

> 建議同時下載 ffmpeg（見下方說明），以獲得最佳影片品質。

---

## 功能特色

- 📍 自動下載 OpenStreetMap 底圖
- 🎨 路線以坡度上色（上坡橘紅、下坡藍青）
- 📊 動態儀表板：距離 / 海拔 / 累積上坡 / 累積下坡
- 🏔️ 高度剖面圖（含 100m 間隔虛線）
- 🗺️ 支援自訂地標標籤（locationGPS.xlsx）
- 🎬 支援多種解析度（720p / 1080p / 2K / 4K，直式 / 橫式）
- ⚡ GPU 加速（需安裝 ffmpeg + NVIDIA）
- 🖥️ GUI 視窗介面，支援批次處理多個 GPX

## 系統需求

- Windows 10/11
- Python 3.11+
- ffmpeg（選用，建議安裝以獲得最佳品質）

## 如何取得 GPX 軌跡檔案

推薦使用 **[gpx.studio](https://gpx.studio/)** 線上繪製健行路線並匯出 GPX。

### 使用 gpx.studio 的步驟

1. 開啟 https://gpx.studio/
2. 在地圖上點擊起點，沿路線依序點擊各個路徑點
3. 完成後點右上角「**Export**」→ 選「**GPX**」格式下載
4. 把下載的 `.gpx` 檔案拖入 HikeReel 即可

> 也可以直接把健行 App（Strava、Garmin Connect、Komoot 等）匯出的 GPX 拖入使用。

---

## 安裝套件

```bash
pip install gpxpy matplotlib numpy opencv-python pillow contextily pyproj rasterio mercantile xyzservices certifi openpyxl
```

## 使用方式

### GUI 模式（推薦）

```bash
python gpx_video_app.py
```

1. 點「＋ 加入檔案」選擇 GPX 檔案（可多選）
2. 修改每個檔案的影片標題
3. 選擇地標資料庫（locationGPS.xlsx）
4. 設定解析度、加速倍數
5. 點「▶ 開始批次產生影片」

### 命令列模式

```bash
python gpx_to_video.py your_track.gpx --title "路線名稱" --speed 15
```

主要參數：
| 參數 | 說明 | 預設值 |
|---|---|---|
| `--title` | 影片標題 | GPX 檔名 |
| `--speed` | 加速倍數 | 15 |
| `--width` / `--height` | 解析度 | 720 / 1280 |
| `--landmarks` | 地標資料庫路徑 | - |
| `--radius` | 地標篩選半徑 (km) | 0.5 |
| `--no-basemap` | 不下載底圖 | - |
| `--no-gpu` | 不使用 GPU | - |

## 地標資料庫格式（locationGPS.xlsx）

| 名稱 | 座標 | 路線標籤 | 備註 |
|---|---|---|---|
| 第一山屋\nRifugio Auronzo | 46.61232, 12.29588 | 三尖峰 | - |

- 座標格式：`緯度, 經度`（直接從 Google Maps 右鍵複製）
- 名稱可用 `\n` 換行（中文在上、外文在下）

## ffmpeg 安裝（強烈建議）

### 為什麼需要 ffmpeg？

HikeReel 產生影片時有兩種編碼方式：

| | 有 ffmpeg | 沒有 ffmpeg |
|---|---|---|
| 影片品質 | ⭐⭐⭐ H.264，各平台通用 | ⭐ mp4v，部分手機/平放器可能無法播放 |
| 速度 | 快（支援 NVIDIA GPU 加速） | 較慢 |
| YouTube / IG 相容性 | ✅ 完全相容 | ⚠️ 部分平台可能拒絕上傳 |

沒有 ffmpeg 程式仍然可以運作，但**強烈建議安裝**，特別是要上傳到 YouTube / Instagram 的情況。

### 安裝方式

**方式 A：用 winget 安裝（推薦，自動加入 PATH）**

在命令提示字元（CMD）執行：
```
winget install Gyan.FFmpeg
```
安裝完成後重新開啟程式即可自動偵測。

**方式 B：手動下載（不需要安裝程式）**

1. 到 https://www.gyan.dev/ffmpeg/builds/ 下載 `ffmpeg-release-essentials.zip`
2. 解壓縮，找到 `binfmpeg.exe`
3. 把 `ffmpeg.exe` 複製到和 `HikeReel.exe`（或 `gpx_video_app.py`）**同一個資料夾**

程式啟動時會自動找到同資料夾的 `ffmpeg.exe`，不需要任何設定。

### 確認是否安裝成功

在命令提示字元執行：
```
ffmpeg -version
```
若顯示版本號即表示安裝成功。

---

## 打包成 .exe

請參閱 `打包說明.txt`

## 解析度選項

| 選項 | 用途 |
|---|---|
| 720 × 1280 | 手機直式 HD（YouTube Shorts）|
| 1080 × 1920 | 手機直式 Full HD |
| 1440 × 2560 | 手機直式 2K |
| 2160 × 3840 | 手機直式 4K |
| 810 × 1440 | 平板直式 |
| 1280 × 720 | 電腦橫式 HD |
| 1920 × 1080 | 電腦橫式 Full HD |
| 2560 × 1440 | 電腦橫式 2K |
| 3840 × 2160 | 電腦橫式 4K |

## 開發者

**Skypray Huang**　首版日期：2026/6/21

## 授權

MIT License
