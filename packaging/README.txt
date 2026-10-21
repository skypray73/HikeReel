HikeReel v2.0.2（2026/10/21）— GPX 健行軌跡 → 動態影片
https://github.com/skypray73/HikeReel

【開始使用】
1. 整個資料夾放在純英文路徑（例如 D:\HikeReel_v2.0.2），不要只複製 HikeReel.exe，
   _internal 資料夾是程式需要的套件，不能刪除或移動。
2. 執行 HikeReel.exe。第一次開啟若出現 SmartScreen 警告，按「其他資訊」→「仍要執行」。
3. 建議安裝 ffmpeg（影片品質與相容性較好）：在命令提示字元執行 winget install Gyan.FFmpeg

【兩種模式】
- 2D：OpenStreetMap 平面地圖，免金鑰。
- 3D：Esri 高解析衛星影像＋地形飛行，需要你自己的 ArcGIS Location Platform 金鑰（免費申請），
  第一次選 3D 時程式會提示輸入。金鑰只存在你這台電腦，不會上傳。

【地標與照片】
- locationGPS.xlsx 是地標資料庫範本（名稱、座標）。
- 按「管理地標照片…」幫地標挑照片；照片會放在 landmark_photos 資料夾。
  走到有照片的地標時影片會停下來顯示照片（預設 3 秒），沒有照片的地標不會停。

【版權與授權】
- HikeReel 程式碼：Copyright (c) 2026 Skypray Huang，MIT License（見 LICENSE）。
- 2D 底圖：© OpenStreetMap contributors（ODbL）。
- 3D 衛星影像：Powered by Esri（Esri World Imagery，依 Esri 使用條款；營利或商業用途請先確認條款）。
- 3D 地形：AWS Terrain Tiles（Mapzen，含 SRTM 等資料）。
- 影片畫面上的來源標示，公開分享時請保留。
- 程式內「版權與授權資訊」有完整的第三方元件授權清單。
