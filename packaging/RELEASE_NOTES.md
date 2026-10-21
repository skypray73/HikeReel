## HikeReel v2.0.4（2026/10/21）

GPX 健行軌跡 → 動態影片。v2.0 新增 **3D 地形飛行模式**與**地標照片**；v2.0.1～v2.0.4 修正問題並改進。

### 🔧 v2.0.4 更新

- **一鍵下載 ffmpeg**：第一次啟動若偵測不到 ffmpeg，提示視窗可直接「同意並下載」，不需要 winget、不必重新開啟程式。
  - 來源：[gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 的 FFmpeg Windows 建置（release essentials，約 110 MB）；下載後以 SHA-256 驗證，不符就不安裝。
  - 授權：該建置為 **GPL v3**；ffmpeg 是 [FFmpeg 專案](https://ffmpeg.org/)的獨立軟體，不是 HikeReel 的一部分，HikeReel 只以外部程式呼叫、未修改。提示視窗、README、程式內「版權與授權資訊」都有寫明。
  - 只會放 `ffmpeg.exe`、`ffmpeg_LICENSE.txt`、`ffmpeg_SOURCE.txt` 到 HikeReel 資料夾（不能寫入時放 `%LOCALAPPDATA%\HikeReel\ffmpeg`）；不想用時刪除 `ffmpeg.exe` 即可。
- 「用 winget 安裝」改為 `winget install Gyan.FFmpeg --source winget`，避開 `msstore` 來源憑證錯誤（`0x8a15005e`）。
- 地標資料庫 `locationGPS.xlsx` 更新（部分地標改名，例如「停車場」→「三尖峰停車場」、「三尖峰側面」→「拉瓦雷多埡口」）。

### 🔧 v2.0.3 更新

- **3D 地標文字不再抖動**：快速移動時，地標標籤改以次像素平滑移動（標籤先以 2 倍解析度繪製成圖片，再用浮點座標貼上），字形不再因每格四捨五入到整數像素而顫動。實測移動中的標籤「每格跳動 ≥1 像素」的比例由 79% 降到 4%。
- 標籤彼此重疊時改為淡出（不再瞬間消失/出現），上一格已顯示的標籤優先保留。
- 走到地標附近時只換醒目顏色，不再放大字體，標籤大小保持穩定。

### 🔧 v2.0.2 更新

- **3D 儀表板重新設計，不再佔滿畫面**：
  - 橫式：距離 / 海拔 / 上坡 / 下坡（2×2）與高度剖面縮成**左下角一塊**（約 1/3 寬），和 2D 橫式的左欄比例相近。
  - 直式：**數字列在最上方、高度剖面在最底部**，合計約 28% 高度（與 2D 直式相近），中間完整留給 3D 畫面。
- 來源標示加上半透明底色，在亮色地形上也看得清楚（影片中須保留）。

### 🔧 v2.0.1 更新

- **修正**：程式所在資料夾不能寫入時（例如放在受保護的位置），啟動會出現「無法建立 .contextily_cache」錯誤而無法使用；現在改用 `%LOCALAPPDATA%\HikeReel` 存放地圖快取。**v2.0 的使用者請更新。**
- **3D 結尾**：抵達終點前不再提早拉遠；登山小人停在終點後，鏡頭才花約 4 秒慢慢拉遠，完整呈現整段軌跡與最終數據。
- **3D 儀表板**：距離 / 海拔 / 上坡 / 下坡四格與高度剖面改用和 2D 模式相同的配色與版型（保留半透明底色）。
- **3D 開場 / 結尾總覽**：整條路線會移到儀表板以外的空白區域，不被遮住。

### 📥 下載（Windows）

下載下方 **`HikeReel_v2.0.4_Windows.zip`**，**整個解壓縮**到純英文路徑（例如 `D:\HikeReel_v2.0.4`），執行 `HikeReel.exe`。

```
HikeReel_v2.0.4/
├─ HikeReel.exe       主程式
├─ _internal/         程式需要的套件（不要刪除或移動）
├─ locationGPS.xlsx   地標資料庫範本
├─ LICENSE
└─ README.txt
```

> - v2.0 起改為「主程式＋套件資料夾」，主程式本身很小、啟動更快；請保留 `_internal` 資料夾。
> - 執行檔未經程式碼簽章，Windows SmartScreen 可能顯示警告，請按「其他資訊」→「仍要執行」。
> - 建議安裝 ffmpeg：`winget install Gyan.FFmpeg --source winget`。
> - 執行檔由 GitHub Actions 依本儲存庫原始碼自動編譯。

### ✨ v2.0 新功能

- **2D / 3D 模式切換**
  - 2D：OpenStreetMap 平面地圖，免金鑰。
  - 3D：Esri 高解析衛星影像貼在真實地形上；第一次選 3D 會提示輸入你自己的 ArcGIS 金鑰（免費申請，程式會先測試再儲存，只存在本機）。
- **3D 登山小人**：背包、登山杖，沿路線走路前進；鏡頭低角度跟隨，看得出地形起伏；急轉彎、之字形路段也不晃動。
- **3D 外圍地形與遠景霧化**：地形延伸到地平線，不再像一座孤島。
- **地標照片（2D、3D 都適用）**：「管理地標照片…」幫地標挑照片；走到地標時停下顯示照片卡片（預設 3 秒），自動轉正、自動裁切；沒有照片的地標不顯示、不停留。
- **2D 影片加上「© OpenStreetMap contributors」來源標示**（OSM 授權要求）。
- 範例 GPX：以「柴山夜爬」取代「高雄壽山_好漢亭」。
- 支援公司 / 學校網路的 SSL 檢查（自動使用 Windows 系統憑證）。

### 🗺️ 資料來源與授權

| 資料 | 來源 / 授權 |
|---|---|
| 2D 底圖 | © OpenStreetMap contributors（ODbL） |
| 3D 衛星影像 | Powered by Esri · Esri World Imagery（需自備金鑰，依 Esri 使用條款；營利或商業用途請先確認條款） |
| 3D 地形 | AWS Terrain Tiles（Mapzen，含 SRTM 等資料） |

影片畫面上的來源標示，公開分享時請保留。完整授權說明見 [README](https://github.com/skypray73/HikeReel#版權與授權) 與程式內「版權與授權資訊」。

HikeReel 程式碼：Copyright © 2026 Skypray Huang，MIT License。
