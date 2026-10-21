#!/usr/bin/env python3
"""
HikeReel — GPX 健行軌跡 → 動態影片（GUI，支援多檔批次）
  2D：OpenStreetMap 平面地圖
  3D：Esri 高解析衛星影像 + 3D 地形飛行（需自備 ArcGIS 金鑰）
Copyright (c) 2026 Skypray Huang — MIT License
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading, os, sys, queue, ctypes

# ── DPI 感知 ──────────────────────────────────────────────────
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

APP_VERSION = "2.0.1"
RELEASE_DATE = "2026/10/21"

BG, PANEL, ACCENT = "#1a1a2e", "#16213e", "#e94560"
TEXT, DIM, SUCCESS, GOLD, DARK2 = "#eaeaea", "#888899", "#00e676", "#ffc864", "#0f1932"


LICENSE_TEXT = f"""HikeReel v{APP_VERSION}（{RELEASE_DATE}）
Copyright (c) 2026 Skypray Huang
本程式以 MIT License 釋出，完整條文見程式資料夾或 GitHub 的 LICENSE 檔。
https://github.com/skypray73/HikeReel

━━ 地圖與影像資料（影片中會自動標示來源）━━
• 2D 底圖：OpenStreetMap
  © OpenStreetMap contributors，資料授權 ODbL（opendatacommons.org/licenses/odbl）。
  圖磚依 OSM 圖磚使用政策取得並快取在本機，請勿大量下載。
• 3D 衛星影像：Esri World Imagery（需自備 ArcGIS Location Platform 金鑰）
  Powered by Esri · Source: Esri, Vantor, GeoEye, Earthstar Geographics, CNES/Airbus DS,
  USDA, USGS, AeroGRID, IGN, and the GIS User Community。
  依 Esri 使用條款使用；圖磚最多暫存 24 小時。影片公開分享須保留畫面上的來源標示，
  營利或商業用途請先確認 Esri 條款。HikeReel 不提供、也不內建任何金鑰。
• 3D 地形高程：AWS Terrain Tiles（Mapzen Terrarium）
  資料來源含 SRTM、GMTED、ETOPO1、EU-DEM 等，詳見
  github.com/tilezen/joerd/blob/master/docs/attribution.md
• 命令列版另可選：OpenTopoMap（CC BY-SA）、Sentinel-2 cloudless 2016（EOX，CC BY 4.0）、
  Sentinel-2 cloudless 2024（EOX，CC BY-NC-SA 4.0，僅限非商業）。

━━ 你提供的內容 ━━
• GPX 軌跡、地標資料庫、地標照片的版權屬於原作者；請確認你有權使用與公開。

━━ 使用的開源元件 ━━
Python（PSF License）、NumPy（BSD）、Matplotlib（PSF-based）、OpenCV（Apache-2.0）、
Pillow（MIT-CMU）、gpxpy（Apache-2.0）、contextily（BSD）、pyproj（MIT）、rasterio（BSD）、
mercantile（BSD）、xyzservices（BSD）、certifi（MPL-2.0）、openpyxl（MIT）、
PyVista（MIT）、VTK（BSD）、truststore（MIT）、FFmpeg（LGPL/GPL，另行安裝）。
"""


class App:
    def __init__(self, root):
        self.root = root
        self.root.title(f"HikeReel v{APP_VERSION}")
        self.root.configure(bg=BG)
        self.root.resizable(True, True)
        root.update_idletasks()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        # 視窗高度取螢幕的 85%，寬度依比例（直式偏窄）
        H = int(sh * 0.85)
        W = max(720, int(H * 0.62))      # 寬約高的 0.62，最小 720
        W = min(W, int(sw * 0.6))         # 不超過螢幕寬 60%
        self.root.minsize(680, 760)
        root.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")

        self.lm_var     = tk.StringVar(value=self._find_lm())
        self.speed_var  = tk.StringVar(value="15")
        self.radius_var = tk.StringVar(value="0.5")
        self.bm_var     = tk.BooleanVar(value=True)
        self.mode_var   = tk.StringVar(value="2d")          # "2d" = OpenStreetMap 平面、"3d" = Esri 3D 地形
        self.sec3d_var  = tk.StringVar(value="40")
        self.photo_dir_var = tk.StringVar(value=self._default_photo_dir())
        self.photo_sec_var = tk.StringVar(value="3")

        # 解析度清單：(顯示名稱, 寬, 高)
        self.RES_OPTIONS = [
            # ── 直式（手機/短影片，9:16）──
            ("📱 720 × 1280   手機直式 HD",          720,  1280),
            ("📱 1080 × 1920  手機直式 Full HD",     1080, 1920),
            ("📱 1440 × 2560  手機直式 2K",          1440, 2560),
            ("📱 2160 × 3840  手機直式 4K",          2160, 3840),
            # ── 直式（平板 9:16）──
            ("🖥  810 × 1440  平板直式",              810,  1440),
            # ── 橫式（電腦/YouTube，16:9）──
            ("🖥  1280 × 720  電腦橫式 HD",          1280,  720),
            ("🖥  1920 × 1080 電腦橫式 Full HD",     1920, 1080),
            ("🖥  2560 × 1440 電腦橫式 2K",          2560, 1440),
            ("🖥  3840 × 2160 電腦橫式 4K",          3840, 2160),
        ]
        self.res_var = tk.StringVar(
            value=self.RES_OPTIONS[0][0])   # 預設第一項 720×1280
        self.log_q      = queue.Queue()
        self.running    = False

        self._ui()
        self._poll()

    def _default_photo_dir(self):
        import landmark_photos as lp
        lm = self.lm_var.get().strip() if hasattr(self, "lm_var") else ""
        return lp.default_folder(lm) if lm else os.path.join(BASE_DIR, lp.DEFAULT_FOLDER)

    def _find_lm(self):
        p = os.path.join(BASE_DIR, "locationGPS.xlsx")
        return p if os.path.exists(p) else ""

    def _ui(self):
        canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self.frame = tk.Frame(canvas, bg=BG)
        self.fid = canvas.create_window((0,0), window=self.frame, anchor="nw")
        self.frame.bind("<Configure>",
                        lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(self.fid, width=e.width))
        # 滑鼠滾軸：依滑鼠所在位置決定捲哪個 canvas
        def _on_scroll(e):
            w = e.widget
            # 往上找到 Canvas
            while w and not isinstance(w, tk.Canvas):
                try:
                    w = w.master
                except Exception:
                    break
            if w is None:
                return
            w.yview_scroll(int(-1 * (e.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_scroll)

        f = self.frame
        tk.Label(f, text=f"HikeReel v{APP_VERSION}", bg=BG, fg=GOLD,
                 font=("Microsoft JhengHei UI", 20, "bold")).pack(pady=(20,2))
        tk.Label(f, text=f"開發：Skypray Huang　　首版日期：2026/6/21　　最新日期：{RELEASE_DATE}",
                 bg=BG, fg=DIM,
                 font=("Microsoft JhengHei UI", 10)).pack(pady=(0,4))
        about = tk.Label(f, text="版權與授權資訊", bg=BG, fg="#7fb3ff", cursor="hand2",
                         font=("Microsoft JhengHei UI", 10, "underline"))
        about.pack(pady=(0,14))
        about.bind("<Button-1>", lambda e: self._about())

        # ① GPX（多檔，每個可自訂標題）
        self._sec(f, "① GPX 軌跡檔案（可一次選多個，標題可個別修改）")
        r1 = tk.Frame(f, bg=BG); r1.pack(fill="x", padx=20, pady=5)
        self._btn(r1, "＋ 加入檔案", self._add_gpx).pack(side="left")
        self._btn(r1, "清空", self._clear_gpx).pack(side="left", padx=(8,0))

        # 表頭
        hdr = tk.Frame(f, bg=BG); hdr.pack(fill="x", padx=20, pady=(8,0))
        tk.Label(hdr, text="檔案名稱", bg=BG, fg=DIM, width=24, anchor="w",
                 font=("Microsoft JhengHei UI", 9)).pack(side="left", padx=(4,0))
        tk.Label(hdr, text="影片標題（可修改）", bg=BG, fg=DIM, anchor="w",
                 font=("Microsoft JhengHei UI", 9)).pack(side="left", padx=(8,0))

        # 可捲動的檔案列表容器
        list_outer = tk.Frame(f, bg=DARK2, height=220)
        list_outer.pack(fill="x", padx=20, pady=(2,0))
        list_outer.pack_propagate(False)

        self.list_canvas = tk.Canvas(list_outer, bg=DARK2, highlightthickness=0)
        list_vsb = tk.Scrollbar(list_outer, command=self.list_canvas.yview)
        self.list_canvas.configure(yscrollcommand=list_vsb.set)
        list_vsb.pack(side="right", fill="y")
        self.list_canvas.pack(side="left", fill="both", expand=True)

        self.rows_frame = tk.Frame(self.list_canvas, bg=DARK2)
        self.rows_id = self.list_canvas.create_window(
            (0,0), window=self.rows_frame, anchor="nw")
        self.rows_frame.bind("<Configure>",
            lambda e: self.list_canvas.configure(
                scrollregion=self.list_canvas.bbox("all")))
        self.list_canvas.bind("<Configure>",
            lambda e: self.list_canvas.itemconfig(self.rows_id, width=e.width))

        # 儲存每列的 widget 和標題變數
        self.file_rows = []   # [{path, title_var, frame}]

        # ② 地標庫
        self._sec(f, "② 地標資料庫（預設載入同目錄內的 locationGPS.xlsx）")
        r2 = tk.Frame(f, bg=BG); r2.pack(fill="x", padx=20, pady=5)
        tk.Entry(r2, textvariable=self.lm_var, bg=PANEL, fg=TEXT,
                 insertbackground=TEXT, relief="flat",
                 font=("Microsoft JhengHei UI", 11), bd=6
                 ).pack(side="left", fill="x", expand=True)
        self._btn(r2, "選擇", self._pick_lm).pack(side="left", padx=(8,0))

        # ③ 模式
        self._sec(f, "③ 模式")
        mf = tk.Frame(f, bg=PANEL); mf.pack(fill="x", padx=20, pady=4)
        for val, text, hint in (
                ("2d", "2D　OpenStreetMap 平面地圖", "免金鑰；依「加速倍數」決定影片長度"),
                ("3d", "3D　Esri 高解析衛星影像＋地形飛行", "需自備 ArcGIS 金鑰（免費申請）")):
            row = tk.Frame(mf, bg=PANEL); row.pack(fill="x", padx=10, pady=3)
            tk.Radiobutton(row, text=text, value=val, variable=self.mode_var, command=self._on_mode,
                           bg=PANEL, fg=TEXT, selectcolor=DARK2, activebackground=PANEL,
                           activeforeground=GOLD, font=("Microsoft JhengHei UI", 11)).pack(side="left")
            tk.Label(row, text=hint, bg=PANEL, fg=DIM,
                     font=("Microsoft JhengHei UI", 9)).pack(side="left", padx=8)
        self.f3d = tk.Frame(mf, bg=PANEL)
        r3 = tk.Frame(self.f3d, bg=PANEL); r3.pack(fill="x", padx=14, pady=(2, 6))
        tk.Label(r3, text="3D 影片長度（秒）", bg=PANEL, fg=TEXT,
                 font=("Microsoft JhengHei UI", 11)).pack(side="left")
        tk.Entry(r3, textvariable=self.sec3d_var, bg=DARK2, fg=GOLD, insertbackground=GOLD,
                 relief="flat", font=("Consolas", 12), width=6).pack(side="left", padx=8)
        tk.Label(r3, text="不含地標照片停留時間", bg=PANEL, fg=DIM,
                 font=("Microsoft JhengHei UI", 9)).pack(side="left")
        r4 = tk.Frame(self.f3d, bg=PANEL); r4.pack(fill="x", padx=14, pady=(0, 8))
        self.key_lbl = tk.Label(r4, text="", bg=PANEL, fg=DIM, font=("Microsoft JhengHei UI", 10))
        self.key_lbl.pack(side="left")
        self._btn(r4, "設定 ArcGIS 金鑰", self._key_dialog).pack(side="left", padx=8)

        # ④ 地標照片
        self._sec(f, "④ 地標照片（2D、3D 都適用；沒有照片的地標不顯示、不停留）")
        r5 = tk.Frame(f, bg=BG); r5.pack(fill="x", padx=20, pady=5)
        tk.Entry(r5, textvariable=self.photo_dir_var, bg=PANEL, fg=TEXT,
                 insertbackground=TEXT, relief="flat",
                 font=("Microsoft JhengHei UI", 10), bd=6).pack(side="left", fill="x", expand=True)
        self._btn(r5, "資料夾", self._pick_photo_dir).pack(side="left", padx=(8,0))
        r6 = tk.Frame(f, bg=BG); r6.pack(fill="x", padx=20, pady=(2,4))
        self._btn(r6, "🖼  管理地標照片…", self._photo_dialog).pack(side="left")
        tk.Label(r6, text="　每張停留（秒）", bg=BG, fg=TEXT,
                 font=("Microsoft JhengHei UI", 11)).pack(side="left")
        tk.Entry(r6, textvariable=self.photo_sec_var, bg=DARK2, fg=GOLD, insertbackground=GOLD,
                 relief="flat", font=("Consolas", 12), width=5).pack(side="left", padx=6)
        tk.Label(r6, text="建議 2.5～3.5", bg=BG, fg=DIM,
                 font=("Microsoft JhengHei UI", 9)).pack(side="left")

        # ⑤ 設定
        self._sec(f, "⑤ 設定")
        pf = tk.Frame(f, bg=PANEL); pf.pack(fill="x", padx=20, pady=4)
        # 解析度選單
        tk.Label(pf, text="輸出解析度", bg=PANEL, fg=TEXT,
                 font=("Microsoft JhengHei UI", 11), width=20, anchor="w"
                 ).grid(row=0, column=0, sticky="w", padx=14, pady=6)
        res_names = [r[0] for r in self.RES_OPTIONS]
        res_menu = ttk.Combobox(pf, textvariable=self.res_var,
                                values=res_names, state="readonly",
                                font=("Microsoft JhengHei UI", 10), width=32)
        res_menu.grid(row=0, column=1, columnspan=2, sticky="w", padx=8, pady=6)

        self._prow(pf, "加速倍數（2D）",  self.speed_var,  "推薦 10~20", 1)
        self._prow(pf, "地標篩選半徑(km)", self.radius_var, "預設 0.5", 2)

        # 大顆勾選框（自繪，明顯）
        cb = tk.Frame(pf, bg=PANEL); cb.grid(row=3, column=0, columnspan=3,
                                              sticky="w", padx=14, pady=10)
        self.bm_btn = tk.Label(cb, text="☑", bg=PANEL, fg=SUCCESS,
                               font=("Segoe UI Symbol", 18), cursor="hand2")
        self.bm_btn.pack(side="left")
        self.bm_btn.bind("<Button-1>", self._toggle_bm)
        lbl = tk.Label(cb, text=" 下載 OpenStreetMap 底圖（2D；需要網路，首次較慢）",
                       bg=PANEL, fg=TEXT, cursor="hand2",
                       font=("Microsoft JhengHei UI", 11))
        lbl.pack(side="left")
        lbl.bind("<Button-1>", self._toggle_bm)

        # 開始按鈕
        self._btn(f, "▶  開始批次產生影片", self._start, big=True
                  ).pack(pady=14, padx=20, fill="x")

        style = ttk.Style(); style.theme_use("clam")
        style.configure("A.Horizontal.TProgressbar",
                        troughcolor=PANEL, background=ACCENT, thickness=8)
        style.configure("TCombobox",
                        fieldbackground=DARK2, background=PANEL,
                        foreground=GOLD, selectbackground=ACCENT,
                        selectforeground="white")
        style.map("TCombobox",
                  fieldbackground=[("readonly", DARK2)],
                  foreground=[("readonly", GOLD)])
        self.prog = ttk.Progressbar(f, mode="determinate", maximum=100,
                                    style="A.Horizontal.TProgressbar")
        self.prog.pack(fill="x", padx=20, pady=(0,4))
        self.prog_label = tk.Label(f, text="", bg=BG, fg=GOLD,
                                   font=("Microsoft JhengHei UI", 10, "bold"))
        self.prog_label.pack(pady=(0,8))

        self._sec(f, "執行記錄")
        self.log = scrolledtext.ScrolledText(
            f, bg=DARK2, fg=TEXT, font=("Consolas", 10),
            state="disabled", wrap="word", height=8, relief="flat",
            padx=10, pady=8)
        self.log.pack(fill="both", expand=True, padx=20, pady=(4,20))

    # ── 模式 / 金鑰 ───────────────────────────────────────────
    def _on_mode(self):
        if self.mode_var.get() == "3d":
            self.f3d.pack(fill="x")
            self._refresh_key_label()
            import terrain3d as t3
            if not t3.arcgis_key():
                if not self._key_dialog():
                    self.mode_var.set("2d")
                    self.f3d.pack_forget()
        else:
            self.f3d.pack_forget()

    def _refresh_key_label(self):
        import terrain3d as t3
        ok = bool(t3.arcgis_key())
        self.key_lbl.config(text="✓ 已設定 ArcGIS 金鑰" if ok else "尚未設定 ArcGIS 金鑰",
                            fg=SUCCESS if ok else "#ffaa44")

    def _key_dialog(self):
        """輸入 ArcGIS 金鑰。回傳是否已設定成功。"""
        import terrain3d as t3, webbrowser
        win = tk.Toplevel(self.root); win.title("設定 ArcGIS 金鑰（3D 模式）")
        win.configure(bg=BG); win.transient(self.root); win.grab_set()
        win.geometry("640x470")
        tk.Label(win, text="3D 模式使用 Esri World Imagery 高解析衛星影像", bg=BG, fg=GOLD,
                 font=("Microsoft JhengHei UI", 13, "bold")).pack(pady=(18, 6))
        msg = ("需要你自己的 ArcGIS Location Platform 金鑰（免費申請，免費額度每月 200 萬張圖磚，"
               "一支影片約 900 張）。\n\n"
               "申請步驟：登入下方網址 →「開發人員認證」→ 建立 API 金鑰 → 選「公開應用程式」→"
               "「無項目存取權」→ 權限只開「底圖 → 靜態底圖圖磚」。\n\n"
               "金鑰只會存在這台電腦的 Windows 使用者環境變數 ARCGIS_API_KEY，不會上傳。\n"
               "使用 Esri 影像製作的影片須保留畫面上的來源標示；營利或商業用途請先確認 Esri 使用條款。")
        tk.Label(win, text=msg, bg=BG, fg=TEXT, justify="left", wraplength=590,
                 font=("Microsoft JhengHei UI", 10)).pack(padx=24, anchor="w")
        link = tk.Label(win, text="https://location.arcgis.com/", bg=BG, fg="#7fb3ff", cursor="hand2",
                        font=("Microsoft JhengHei UI", 10, "underline"))
        link.pack(pady=6)
        link.bind("<Button-1>", lambda e: webbrowser.open("https://location.arcgis.com/"))
        kv = tk.StringVar()
        ent = tk.Entry(win, textvariable=kv, show="•", bg=PANEL, fg=TEXT, insertbackground=TEXT,
                       relief="flat", font=("Consolas", 11), bd=6)
        ent.pack(fill="x", padx=24, pady=6); ent.focus_set()
        st = tk.Label(win, text="", bg=BG, fg=DIM, font=("Microsoft JhengHei UI", 10))
        st.pack()
        result = {"ok": False}

        def save():
            k = kv.get().strip()
            if len(k) < 20 or not k.isascii():
                st.config(text="金鑰格式不對：應為一長串英數字（通常以 AAPT 或 AAPK 開頭）", fg="#ff6666"); return
            st.config(text="測試金鑰中…", fg=DIM); win.update()
            ok, why = t3.check_arcgis_key(k)
            if not ok:
                st.config(text=why, fg="#ff6666"); return
            t3.save_arcgis_key(k)
            result["ok"] = True
            win.destroy()

        bf = tk.Frame(win, bg=BG); bf.pack(pady=12)
        self._btn(bf, "測試並儲存", save).pack(side="left", padx=6)
        self._btn(bf, "取消", win.destroy).pack(side="left", padx=6)
        win.bind("<Return>", lambda e: save())
        self.root.wait_window(win)
        if hasattr(self, "key_lbl"):
            self._refresh_key_label()
        return result["ok"] or bool(t3.arcgis_key())

    # ── 地標照片 ──────────────────────────────────────────────
    def _pick_photo_dir(self):
        d = filedialog.askdirectory(title="選擇地標照片資料夾")
        if d:
            self.photo_dir_var.set(d)

    def _photo_dialog(self):
        import landmark_photos as lp
        from PIL import Image, ImageTk, ImageOps
        lm = self.lm_var.get().strip()
        if not lm or not os.path.exists(lm):
            messagebox.showerror("錯誤", "請先在 ② 選擇地標資料庫"); return
        names = lp.list_landmark_names(lm)
        if not names:
            messagebox.showinfo("提示", "地標資料庫裡沒有地標"); return
        folder = self.photo_dir_var.get().strip() or lp.default_folder(lm)
        table = lp.landmark_photo_table(lm)
        win = tk.Toplevel(self.root); win.title("管理地標照片")
        win.configure(bg=BG); win.transient(self.root); win.geometry("760x640")
        tk.Label(win, text=f"照片會複製到：{folder}\n檔名＝地標名稱第一行；照片會依 EXIF 轉正並自動裁切成 4:3",
                 bg=BG, fg=DIM, justify="left", font=("Microsoft JhengHei UI", 9)).pack(anchor="w", padx=14, pady=8)
        outer = tk.Frame(win, bg=DARK2); outer.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        cv = tk.Canvas(outer, bg=DARK2, highlightthickness=0)
        sb = tk.Scrollbar(outer, command=cv.yview); cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y"); cv.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(cv, bg=DARK2); wid = cv.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfig(wid, width=e.width))
        thumbs = []

        def draw():
            for w in inner.winfo_children():
                w.destroy()
            thumbs.clear()
            for name in names:
                row = tk.Frame(inner, bg=DARK2); row.pack(fill="x", pady=2, padx=4)
                ph = lp.find_photo(name, table, folder)
                if ph:
                    try:
                        im = ImageOps.fit(lp.open_photo(ph), (80, 60))
                        tkimg = ImageTk.PhotoImage(im); thumbs.append(tkimg)
                        tk.Label(row, image=tkimg, bg=DARK2).pack(side="left", padx=4)
                    except Exception:
                        tk.Label(row, text="（無法讀取）", width=10, bg=DARK2, fg="#ff6666").pack(side="left")
                else:
                    tk.Label(row, text="無照片", width=10, height=3, bg="#222240", fg=DIM,
                             font=("Microsoft JhengHei UI", 9)).pack(side="left", padx=4)
                tk.Label(row, text=name.replace("\n", "\n"), bg=DARK2, fg=TEXT, justify="left", anchor="w",
                         font=("Microsoft JhengHei UI", 10)).pack(side="left", fill="x", expand=True, padx=8)
                if ph:
                    tk.Button(row, text="移除", bg="#4a2a2a", fg="white", relief="flat",
                              command=lambda n=name: remove(n)).pack(side="right", padx=4)
                tk.Button(row, text="選擇照片…" if not ph else "更換…", bg="#2a2a4a", fg="white", relief="flat",
                          command=lambda n=name: choose(n)).pack(side="right", padx=4)

        def choose(name):
            src = filedialog.askopenfilename(
                parent=win, title=f"選擇照片：{name.splitlines()[0]}",
                filetypes=[("圖片", "*.jpg *.jpeg *.png *.webp *.heic *.heif *.bmp"), ("所有", "*.*")])
            if src:
                try:
                    lp.open_photo(src)                     # 先確認讀得到
                    lp.save_photo(src, name, folder)
                except Exception as ex:
                    messagebox.showerror("錯誤", f"無法使用這張照片：{ex}", parent=win); return
                draw()

        def remove(name):
            if messagebox.askyesno("移除照片", f"移除「{name.splitlines()[0]}」的照片？\n（只刪除照片資料夾裡的複本）",
                                   parent=win):
                lp.remove_photo(name, folder)
                draw()

        draw()

    def _toggle_bm(self, ev=None):
        self.bm_var.set(not self.bm_var.get())
        self.bm_btn.config(text="☑" if self.bm_var.get() else "☐",
                           fg=SUCCESS if self.bm_var.get() else DIM)

    def _about(self):
        win = tk.Toplevel(self.root); win.title("版權與授權資訊")
        win.configure(bg=BG); win.geometry("720x640")
        txt = scrolledtext.ScrolledText(win, bg=DARK2, fg=TEXT, wrap="word", relief="flat",
                                        font=("Microsoft JhengHei UI", 10), padx=12, pady=10)
        txt.pack(fill="both", expand=True, padx=12, pady=12)
        txt.insert("end", LICENSE_TEXT)
        txt.config(state="disabled")

    def _sec(self, parent, text):
        row = tk.Frame(parent, bg=BG); row.pack(fill="x", padx=20, pady=(12,2))
        tk.Label(row, text=text, bg=BG, fg=GOLD,
                 font=("Microsoft JhengHei UI", 11, "bold")).pack(side="left")

    def _btn(self, parent, text, cmd, big=False):
        font = ("Microsoft JhengHei UI", 14, "bold") if big else \
               ("Microsoft JhengHei UI", 11)
        bg = ACCENT if big else "#2a2a4a"
        return tk.Button(parent, text=text, command=cmd, bg=bg, fg="white",
                         activebackground=bg, activeforeground="white",
                         relief="flat", font=font, cursor="hand2",
                         pady=12 if big else 7, padx=14)

    def _prow(self, parent, label, var, hint, row):
        tk.Label(parent, text=label, bg=PANEL, fg=TEXT,
                 font=("Microsoft JhengHei UI", 11), width=20, anchor="w"
                 ).grid(row=row, column=0, sticky="w", padx=14, pady=6)
        tk.Entry(parent, textvariable=var, bg=DARK2, fg=GOLD,
                 insertbackground=GOLD, relief="flat",
                 font=("Consolas", 12), width=12
                 ).grid(row=row, column=1, padx=10, pady=6)
        tk.Label(parent, text=hint, bg=PANEL, fg=DIM,
                 font=("Microsoft JhengHei UI", 10)
                 ).grid(row=row, column=2, sticky="w", padx=4, pady=6)

    # ── GPX 清單 ──────────────────────────────────────────────
    def _add_gpx(self):
        paths = filedialog.askopenfilenames(
            title="選擇 GPX 檔案（可多選）",
            filetypes=[("GPX", "*.gpx"), ("所有", "*.*")])
        existing = {r["path"] for r in self.file_rows}
        for p in paths:
            if p in existing:
                continue
            self._add_file_row(p)

    def _add_file_row(self, path):
        """新增一列：左邊檔名、右邊可編輯標題輸入框"""
        default_title = os.path.splitext(os.path.basename(path))[0]
        title_var = tk.StringVar(value=default_title)

        row = tk.Frame(self.rows_frame, bg=DARK2)
        row.pack(fill="x", pady=1)

        # 檔名（唯讀標籤）
        tk.Label(row, text=os.path.basename(path), bg=DARK2, fg=TEXT,
                 width=24, anchor="w",
                 font=("Microsoft JhengHei UI", 10)
                 ).pack(side="left", padx=(4,0))
        # 標題輸入框（可編輯）
        tk.Entry(row, textvariable=title_var, bg="#1a2a4a", fg=GOLD,
                 insertbackground=GOLD, relief="flat",
                 font=("Microsoft JhengHei UI", 10)
                 ).pack(side="left", fill="x", expand=True, padx=(8,4), pady=2)
        # 移除按鈕
        btn = tk.Label(row, text="✕", bg=DARK2, fg="#ff6666",
                       font=("Microsoft JhengHei UI", 11, "bold"),
                       cursor="hand2")
        btn.pack(side="right", padx=6)

        rec = {"path": path, "title_var": title_var, "frame": row}
        btn.bind("<Button-1>", lambda e, r=rec: self._remove_row(r))
        self.file_rows.append(rec)

    def _remove_row(self, rec):
        rec["frame"].destroy()
        self.file_rows.remove(rec)

    def _clear_gpx(self):
        for r in self.file_rows:
            r["frame"].destroy()
        self.file_rows.clear()

    def _pick_lm(self):
        p = filedialog.askopenfilename(
            title="選擇地標資料庫",
            filetypes=[("Excel/CSV", "*.xlsx *.xls *.csv"), ("所有", "*.*")])
        if p:
            self.lm_var.set(p)
            import landmark_photos as lp
            self.photo_dir_var.set(lp.default_folder(p))

    # ── 日誌 ──────────────────────────────────────────────────
    def _append(self, msg, color=None):
        self.log_q.put((msg, color or TEXT))

    def _poll(self):
        try:
            while True:
                msg, col = self.log_q.get_nowait()
                self.log.config(state="normal")
                tag = f"t{abs(hash(col))}"
                self.log.tag_config(tag, foreground=col)
                self.log.insert("end", msg + "\n", tag)
                self.log.see("end")
                self.log.config(state="disabled")
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    # ── 進度條更新（thread-safe）──────────────────────────────
    def _set_progress(self, pct, text=""):
        def update():
            self.prog["value"] = pct
            if text:
                self.prog_label.config(text=text)
        self.root.after(0, update)

    # ── 批次產生 ──────────────────────────────────────────────
    def _start(self):
        if not self.file_rows:
            messagebox.showerror("錯誤", "請先加入至少一個 GPX 檔案")
            return
        if self.mode_var.get() == "3d":
            import terrain3d as t3
            if not t3.arcgis_key() and not self._key_dialog():
                messagebox.showinfo("提示", "3D 模式需要 ArcGIS 金鑰。可以改用 2D 模式。")
                return
        if self.running:
            messagebox.showinfo("提示", "正在產生中，請稍候…")
            return
        self.running = True
        self.prog["value"] = 0
        self.prog_label.config(text="準備中…")
        threading.Thread(target=self._run_batch, daemon=True).start()

    def _run_batch(self):
        import builtins, traceback
        orig_print = builtins.print

        def my_print(*args, **kwargs):
            msg = " ".join(str(a) for a in args)
            col = SUCCESS if ("✅" in msg or "完成" in msg) else \
                  "#ff6666" if "❌" in msg else \
                  DIM if msg.startswith("   ") else TEXT
            self._append(msg, col)
        builtins.print = my_print

        try:
            # 在主執行緒外先把 path + title 取出（避免跨執行緒存取 tk 變數）
            jobs = [(r["path"], r["title_var"].get().strip())
                    for r in self.file_rows]
            total_files = len(jobs)
            self._append("=" * 48, GOLD)
            self._append(f"▶ 批次處理 {total_files} 個檔案", GOLD)

            ok_count = 0
            for idx, (gpx, title) in enumerate(jobs, 1):
                self._append(f"\n【{idx}/{total_files}】{os.path.basename(gpx)}", GOLD)
                if title:
                    self._append(f"   標題：{title}", DIM)
                try:
                    self._make_one(gpx, title, idx, total_files)
                    ok_count += 1
                except Exception as ex:
                    self._append(f"   ❌ 此檔失敗：{ex}", "#ff6666")
                self._set_progress(idx / total_files * 100,
                                   f"完成 {idx}/{total_files}")

            self._append(f"\n{'='*48}", GOLD)
            self._append(f"✅ 全部完成！成功 {ok_count}/{total_files}", SUCCESS)
            self.root.after(0, lambda: messagebox.showinfo(
                "完成！", f"批次處理完成\n成功 {ok_count}/{total_files} 個"))

        except Exception as ex:
            self._append(f"❌ 錯誤：{ex}", "#ff6666")
            self._append(traceback.format_exc(), DIM)
        finally:
            builtins.print = orig_print
            self.running = False
            self.root.after(0, lambda: self._set_progress(100, "全部完成 ✓"))

    def _make_one(self, gpx, title="", file_idx=1, file_total=1):
        if self.mode_var.get() == "3d":
            return self._make_one_3d(gpx, title, file_idx, file_total)
        return self._make_one_2d(gpx, title, file_idx, file_total)

    def _res(self):
        W, H = 720, 1280
        for name, w, h in self.RES_OPTIONS:
            if name == self.res_var.get():
                W, H = w, h
                break
        return W + W % 2, H + H % 2

    def _make_one_3d(self, gpx, title="", file_idx=1, file_total=1):
        import terrain3d as t3
        W, H = self._res()
        argv = [gpx, "--texture", "esri", "--seconds", self.sec3d_var.get() or "40", "--fps", "30",
                "--width", str(W), "--height", str(H),
                "--radius", self.radius_var.get() or "0.5",
                "--photo-seconds", self.photo_sec_var.get() or "3",
                "--output", f"{os.path.splitext(gpx)[0]} 3D ({W}x{H}).mp4"]
        if title:
            argv += ["--title", title]
        lm = self.lm_var.get().strip()
        if lm and os.path.exists(lm):
            argv += ["--landmarks", lm]
        else:
            argv += ["--no-landmarks"]
        if self.photo_dir_var.get().strip():
            argv += ["--photos", self.photo_dir_var.get().strip()]
        args = t3.build_parser().parse_args(argv)

        def prog(frac):
            self._set_progress((file_idx - 1 + frac) / file_total * 100,
                               f"檔案 {file_idx}/{file_total}　本檔 {frac*100:.0f}%")
        try:
            out = t3.render(args, progress=prog)
        except SystemExit as e:
            raise RuntimeError(str(e))
        self._append(f"   ✅ 輸出：{os.path.basename(out)}", SUCCESS)

    def _make_one_2d(self, gpx, title="", file_idx=1, file_total=1):
        import gpx_to_video as gv
        import landmark_photos as lp
        import cv2, numpy as np
        import shutil as sh, subprocess as sp, time as tm

        lm     = self.lm_var.get().strip()
        speed  = float(self.speed_var.get() or "15")
        radius = float(self.radius_var.get() or "0.5")
        use_bm = self.bm_var.get()

        data = gv.parse_gpx(gpx)
        # 標題：使用者指定優先，否則用檔名
        data["track_name"] = title if title else \
            os.path.splitext(os.path.basename(gpx))[0]

        if lm and os.path.exists(lm):
            gv.WAYPOINTS = gv.load_landmarks(lm, radius,
                                              data["lats"], data["lons"])

        # 解析度：從選單找對應寬高（先算，底圖品質依此調整）
        W, H = self._res()

        # 依解析度決定底圖品質提升等級
        long_side = max(W, H)
        if long_side >= 3840:   q_boost = 3   # 4K
        elif long_side >= 2560: q_boost = 2   # 2K
        elif long_side >= 1920: q_boost = 1   # Full HD
        else:                   q_boost = 0   # HD

        basemap = None
        if use_bm:
            if gv.HAS_CTX:
                self._append("   🌐 下載底圖…", TEXT)
                basemap = gv.get_basemap(data["lats"], data["lons"], q_boost)
                if basemap:
                    self._append("   底圖完成 ✓", SUCCESS)
                else:
                    self._append("   ⚠️ 底圖失敗，用純色背景", "#ffaa44")
            else:
                self._append("   ⚠️ exe 未包含 contextily，無法下載底圖", "#ffaa44")

        bg, map_px, ele_px, ele_base_y, ele_area, \
            dash_cells, is_landscape, frame_w = \
            gv.render_static(data, W, H, basemap)
        if basemap is not None:
            bg = gv.add_osm_credit(bg)            # OSM 授權要求：影片上標示「© OpenStreetMap contributors」

        n = len(data["lats"])
        ea, da = data["eles"], data["dists"]
        seg_colors = []
        for i in range(n):
            if i == 0 or i == n-1:
                seg_colors.append(gv.slope_color_bgr(0))
            else:
                i0, i1 = max(0,i-3), min(n-1,i+3)
                d_e = float(ea[i1]-ea[i0]); d_d = (float(da[i1]-da[i0])*1000)+1e-3
                seg_colors.append(gv.slope_color_bgr(d_e/d_d*100))

        fps = 24
        total = max(60, int(n * fps / speed))

        # 地標照片（與 3D 共用）：走到有照片的地標時停下來顯示照片卡片
        holds = []
        folder = self.photo_dir_var.get().strip() or (lp.default_folder(lm) if lm else "")
        table = lp.landmark_photo_table(lm) if lm and os.path.exists(lm) else {}
        try:
            hold_n = max(1, int(round(float(self.photo_sec_var.get() or "3") * fps)))
        except ValueError:
            hold_n = 3 * fps
        lat_a, lon_a = data["lats"], data["lons"]
        for wp in (gv.WAYPOINTS if lm and os.path.exists(lm) else []):
            name, wlat, wlon = wp[0], wp[1], wp[2]
            ph = lp.find_photo(name, table, folder)
            if not ph:
                continue
            near = int(np.argmin((lat_a - wlat) ** 2 + ((lon_a - wlon) * np.cos(np.radians(wlat))) ** 2))
            try:
                card = lp.PhotoCard(ph, name, W, H, min(W, H) / 720, gv.PIL_FONT)
            except Exception as ex:
                self._append(f"   ⚠️ 照片無法開啟：{ph}（{ex}）", "#ffaa44")
                continue
            holds.append((float(near), hold_n, card))
        if holds:
            self._append(f"   🖼️ 地標照片：{len(holds)} 張", TEXT)
        sched, ranges = lp.build_schedule(float(n - 1), total, holds)
        photo_at = {}
        for a, b, card in ranges:
            for k in range(a, b):
                photo_at[k] = (card, (k - a) / max(1, b - a - 1), k - a, b - a)
        total = len(sched)
        # 輸出檔名：主檔名 + 解析度後綴，例如「三尖峰 (720x1280).mp4」
        base = os.path.splitext(gpx)[0]
        out = f"{base} ({W}x{H}).mp4"

        ffmpeg = gv.find_ffmpeg()
        proc = cv_out = None
        if ffmpeg:
            cmd = [ffmpeg, "-y", "-f", "rawvideo", "-vcodec", "rawvideo",
                   "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                   "-pix_fmt", "yuv420p", out]
            proc = sp.Popen(cmd, stdin=sp.PIPE, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
        else:
            self._append("   ⚠️ 找不到 ffmpeg，改用內建編碼（相容性較低）", "#ffaa44")
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            cv_out = cv2.VideoWriter(out, fourcc, fps, (W, H))

        t0 = tm.time()
        for i in range(total):
            pos = max(1, int(round(sched[i])))
            frame = gv.render_frame(
                bg, map_px, ele_px, ele_base_y, ele_area,
                dash_cells, is_landscape, frame_w,
                data, pos, seg_colors)
            if frame.shape[1] != W or frame.shape[0] != H:
                frame = cv2.resize(frame, (W, H))
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            if i in photo_at:
                card, u, k, nk = photo_at[i]
                fade = max(1, int(fps * 0.3))
                rgb = card.draw(rgb, u, min(1.0, (k + 1) / fade, (nk - k) / fade))
            if proc:
                proc.stdin.write(rgb.tobytes())
            else:
                cv_out.write(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
            if i % max(1, total//10) == 0:
                frame_pct = i / total
                # 總進度 = (已完成檔案 + 當前檔案進度) / 總檔案數
                overall = (file_idx - 1 + frame_pct) / file_total * 100
                self._set_progress(
                    overall,
                    f"檔案 {file_idx}/{file_total}　本檔 {frame_pct*100:.0f}%")
                self._append(f"   進度 {frame_pct*100:.0f}%", DIM)

        if proc:
            proc.stdin.close(); proc.wait()
        if cv_out:
            cv_out.release()
        self._append(f"   ✅ 輸出：{os.path.basename(out)}"
                     f"（{tm.time()-t0:.1f}s）", SUCCESS)


def check_ffmpeg_and_start(root):
    """啟動前檢查 ffmpeg，若無則提示使用者。"""
    import gpx_to_video as gv

    ffmpeg = gv.find_ffmpeg()
    if ffmpeg:
        # 有 ffmpeg，直接進主程式
        App(root)
        return

    # 沒有 ffmpeg，跳出提醒視窗
    popup = tk.Toplevel(root)
    popup.title("HikeReel — 未偵測到 ffmpeg")
    popup.configure(bg=BG)
    popup.resizable(True, True)
    popup.minsize(560, 420)
    popup.grab_set()

    root.update_idletasks()
    pw, ph = 640, 480
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    popup.geometry(f"{pw}x{ph}+{(sw-pw)//2}+{(sh-ph)//2}")

    tk.Label(popup, text="⚠️  未偵測到 ffmpeg",
             bg=BG, fg="#ffaa44",
             font=("Microsoft JhengHei UI", 16, "bold")
             ).pack(pady=(28, 12))

    msg = (
        "沒有 ffmpeg 也能產生影片，\n"
        "但會改用內建編碼（OpenCV mp4v）：\n\n"
        "  • 速度較慢\n"
        "  • 相容性較差（部分播放器可能無法播放）\n"
        "  • 無法使用 NVIDIA GPU 加速\n\n"
        "建議安裝 ffmpeg 以獲得最佳效果。"
    )
    tk.Label(popup, text=msg, bg=BG, fg=TEXT,
             font=("Microsoft JhengHei UI", 12),
             justify="left", anchor="w", wraplength=580
             ).pack(padx=32, pady=8, fill="both", expand=True)


    def install_ffmpeg():
        import subprocess
        popup.destroy()
        # 開一個新命令提示字元執行安裝
        try:
            subprocess.Popen(
                ["cmd", "/c", "winget install Gyan.FFmpeg & pause"],
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
        except Exception:
            messagebox.showinfo(
                "\u63d0\u793a",
                "\u8acb\u5728\u547d\u4ee4\u63d0\u793a\u5b57\u5143\uff08CMD\uff09\u57f7\u884c\uff1a"
                "\n\nwinget install Gyan.FFmpeg\n\n"
                "\u5b89\u88dd\u5b8c\u6210\u5f8c\u91cd\u65b0\u958b\u555f\u7a0b\u5f0f\u3002")
        # 安裝中不進主程式，讓使用者裝完後重開
        root.destroy()

    def skip_install():
        popup.destroy()
        App(root)   # 仍然進入主程式

    # 按鈕區固定在底部置中
    btn_frame = tk.Frame(popup, bg=BG)
    btn_frame.pack(side="bottom", pady=(8, 24))

    tk.Button(btn_frame,
              text="✅ 是，立即安裝 ffmpeg",
              command=install_ffmpeg,
              bg="#2a6e2a", fg="white",
              activebackground="#2a6e2a", activeforeground="white",
              relief="flat", cursor="hand2",
              font=("Microsoft JhengHei UI", 12, "bold"),
              padx=18, pady=10
              ).pack(side="left", padx=(0, 12))

    tk.Button(btn_frame,
              text="否，繼續使用內建編碼",
              command=skip_install,
              bg="#2a2a4a", fg=TEXT,
              activebackground="#2a2a4a", activeforeground=TEXT,
              relief="flat", cursor="hand2",
              font=("Microsoft JhengHei UI", 12),
              padx=18, pady=10
              ).pack(side="left")


def main():
    # 命令列模式：HikeReel.exe --cli2d 參數… / HikeReel.exe --cli3d 參數…（與 gpx_to_video.py / terrain3d.py 相同）
    if len(sys.argv) > 1 and sys.argv[1] in ("--cli2d", "--cli3d"):
        mode = sys.argv.pop(1)
        if mode == "--cli2d":
            import gpx_to_video as gv
            gv.main()
        else:
            import terrain3d as t3
            t3.main()
        return
    root = tk.Tk()
    root.withdraw()   # 先隱藏主視窗，等 ffmpeg 確認後再顯示
    check_ffmpeg_and_start(root)
    root.deiconify()  # 顯示主視窗
    root.mainloop()


if __name__ == "__main__":
    main()
