HikeReel v2.1.1（2026/10/25）— GPX 健行軌跡 → 動態影片
https://github.com/skypray73/HikeReel

【開始使用】
1. 整個資料夾放在純英文路徑（例如 D:\HikeReel_v2.1.1），不要只複製 HikeReel.exe，
   _internal 資料夾是程式需要的套件，不能刪除或移動。
2. 執行 HikeReel.exe。第一次開啟若出現 SmartScreen 警告，按「其他資訊」→「仍要執行」。
3. 第一次啟動若提示找不到 ffmpeg，按「同意並下載 ffmpeg」即可（來源 GitHub：GyanD/codexffmpeg〔備援 gyan.dev〕，GPL v3，SHA-256 驗證，
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

【GPS 照片自動配對（v2.1 新增）】
- 按「匯入 GPS 照片…」批次選照片，讀取 EXIF GPS，不需要 Excel。
- 無 GPS 的照片可在清單中「設定／補上 GPS」，否則產片時略過。
- 清單可切換 GPX 預覽離軌跡距離，並設定選填影片標題、移除匯入項目。
- 預設離軌跡 500 公尺內顯示，可於「地標／照片半徑(km)」調整；0.1＝100 m。
- 使用到軌跡線段的最近平面距離；同樣接近的折返路段採第一次經過，不依時間猜位置。
- 2D／3D 共用，照片停留時間另加到影片；HEIC／HEIF 解碼器已包含。
- 複本在照片資料夾的 gps_imports/，座標在 gps_photos.json。
  原始照片不修改，照片與 GPS 只在本機處理，不上傳。

【GPS 照片標題（v2.1.1）】
- GPS 照片預設不顯示檔名，也不保留空白標題列。
- 需要說明時，在匯入照片清單選照片，再按「設定影片標題」。
  留空並確定即可隱藏標題，清單中的照片名稱僅供辨識。
- 舊版已匯入的照片可直接沿用；Excel 地標照片繼續顯示地標名稱。

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
  Get-FileHash HikeReel_v2.1.1_Windows.zip -Algorithm SHA256
- 被擋時可把 HikeReel 資料夾加入防毒例外，並向廠商回報誤判（Norton：https://submit.norton.com ；
  Microsoft：https://www.microsoft.com/en-us/wdsi/filesubmission）。完整說明見 GitHub 上的 README。
