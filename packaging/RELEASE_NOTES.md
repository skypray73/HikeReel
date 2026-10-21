## HikeReel v2.0（2026/10/21）

GPX 健行軌跡 → 動態影片。這一版新增 **3D 地形飛行模式**與**地標照片**。

### 📥 下載（Windows）

下載下方 **`HikeReel_v2.0_Windows.zip`**，**整個解壓縮**到純英文路徑（例如 `D:\HikeReel_v2.0`），執行 `HikeReel.exe`。

```
HikeReel_v2.0/
├─ HikeReel.exe       主程式
├─ _internal/         程式需要的套件（不要刪除或移動）
├─ locationGPS.xlsx   地標資料庫範本
├─ LICENSE
└─ README.txt
```

> - v2.0 起改為「主程式＋套件資料夾」，主程式本身很小、啟動更快；請保留 `_internal` 資料夾。
> - 執行檔未經程式碼簽章，Windows SmartScreen 可能顯示警告，請按「其他資訊」→「仍要執行」。
> - 建議安裝 ffmpeg：`winget install Gyan.FFmpeg`。
> - 執行檔由 GitHub Actions 依本儲存庫原始碼自動編譯。

### ✨ 新功能

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
