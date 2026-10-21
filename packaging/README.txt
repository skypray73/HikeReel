HikeReel v2.0.4（2026/10/21）— GPX 健行軌跡 → 動態影片
https://github.com/skypray73/HikeReel

【開始使用】
1. 整個資料夾放在純英文路徑（例如 D:\HikeReel_v2.0.4），不要只複製 HikeReel.exe，
   _internal 資料夾是程式需要的套件，不能刪除或移動。
2. 執行 HikeReel.exe。第一次開啟若出現 SmartScreen 警告，按「其他資訊」→「仍要執行」。
3. 第一次啟動若提示找不到 ffmpeg，按「同意並下載 ffmpeg」即可（來源 gyan.dev，GPL v3，SHA-256 驗證，
   只放 ffmpeg.exe 與授權文件到本資料夾；不想用時刪除 ffmpeg.exe）。
   也可自行安裝：winget install Gyan.FFmpeg --source winget

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

【防毒軟體誤判】
HikeReel 沒有程式碼簽章、使用者還不多，Norton 等信譽制防毒可能把它判為「未知／高風險」而封鎖，這通常是誤判。
- 請從 https://github.com/skypray73/HikeReel/releases 下載，並用 Release 說明裡的 SHA-256 核對 zip：
  Get-FileHash HikeReel_v2.0.4_Windows.zip -Algorithm SHA256
- 被擋時可把 HikeReel 資料夾加入防毒例外，並向廠商回報誤判（Norton：https://submit.norton.com ；
  Microsoft：https://www.microsoft.com/en-us/wdsi/filesubmission）。完整說明見 GitHub 上的 README。
