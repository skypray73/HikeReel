"""GPS photo import/coordinate editor for the Tk GUI (MIT License)."""
import math
from pathlib import Path
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

import photo_gps as gps


def show_dialog(app):
    if app.running:
        messagebox.showinfo("提示", "請等影片產生完成後再修改 GPS 照片")
        return
    folder = app.photo_dir_var.get().strip() or app._default_photo_dir()
    app.photo_dir_var.set(folder)
    try:
        records = gps.load_catalog(folder)
    except Exception as ex:
        messagebox.showerror("讀取失敗", str(ex))
        return
    win = tk.Toplevel(app.root)
    win.title("匯入 GPS 照片")
    win.geometry("920x540")
    win.transient(app.root)
    win.grab_set()
    tk.Label(win, text="讀取照片內的 GPS，自動配對到最近的軌跡線段；沒有 GPS 的照片可手動補座標。",
             anchor="w").pack(fill="x", padx=14, pady=(12, 3))
    tk.Label(win, text=f"照片與座標清單儲存在：{folder}", anchor="w", wraplength=870).pack(fill="x", padx=14)
    tk.Label(win, text="預設 500 公尺內才顯示，可於主視窗調整篩選半徑；距離只比較平面位置。",
             anchor="w").pack(fill="x", padx=14, pady=4)

    preview_row = tk.Frame(win)
    preview_row.pack(fill="x", padx=14, pady=5)
    tk.Label(preview_row, text="預覽路線：").pack(side="left")
    jobs = list(app.file_rows)
    choices = [f"{i + 1}. {Path(r['path']).name}" for i, r in enumerate(jobs)]
    route_combo = ttk.Combobox(preview_row, state="readonly", values=choices, width=45)
    route_combo.pack(side="left")
    if choices:
        route_combo.current(0)
    else:
        tk.Label(preview_row, text="先在主視窗加入 GPX 才能預覽距離").pack(side="left")
    body = tk.Frame(win)
    body.pack(fill="both", expand=True, padx=14, pady=6)
    tree = ttk.Treeview(body, columns=("name", "lat", "lon", "distance", "status"), show="headings", selectmode="extended")
    for key, title, width in (("name", "照片名稱", 240), ("lat", "緯度", 110), ("lon", "經度", 110),
                              ("distance", "離軌跡", 100), ("status", "狀態", 230)):
        tree.heading(key, text=title)
        tree.column(key, width=width, minwidth=70)
    bar = ttk.Scrollbar(body, command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    tree.pack(fill="both", expand=True)
    status = tk.StringVar(value="可一次選取多張照片；同一位置的照片會依序顯示。")
    tk.Label(win, textvariable=status, anchor="w", wraplength=870).pack(fill="x", padx=14, pady=3)
    buttons = tk.Frame(win)
    buttons.pack(fill="x", padx=14, pady=(4, 12))
    route_cache = {}
    busy = False

    def refresh(*_):
        nonlocal records
        try:
            records = gps.load_catalog(folder)
            radius = float(app.radius_var.get() or "0.5")
            if not math.isfinite(radius) or radius < 0:
                raise ValueError("篩選半徑必須大於或等於 0")
            data = None
            idx = route_combo.current()
            if idx >= 0:
                path = jobs[idx]["path"]
                if path not in route_cache:
                    from gpx_to_video import parse_gpx
                    route_cache[path] = parse_gpx(path)
                data = route_cache[path]
            tree.delete(*tree.get_children())
            for record in records:
                lat, lon = record["lat"], record["lon"]
                distance, state = "—", "待選擇 GPX 預覽"
                if lat is None or lon is None:
                    state = "無 GPS：請補座標，否則略過"
                elif data is not None:
                    _, offset = gps.nearest_route_position(lat, lon, data["lats"], data["lons"])
                    distance = f"{offset:.1f} m"
                    state = "會顯示" if offset <= radius * 1000 + 1e-6 else "超出篩選半徑：略過"
                if not gps.asset_path(folder, record).is_file():
                    state = "照片檔案遺失：請重新匯入"
                tree.insert("", "end", iid=record["id"], values=(record["name"],
                            f"{lat:.7f}" if lat is not None else "—",
                            f"{lon:.7f}" if lon is not None else "—", distance, state))
        except Exception as ex:
            messagebox.showerror("無法更新照片清單", str(ex), parent=win)

    def set_busy(value):
        nonlocal busy
        busy = value
        for button in (add_button, edit_button, remove_button, rename_button):
            button.configure(state="disabled" if value else "normal")
        route_combo.configure(state="disabled" if value else "readonly")

    def add():
        paths = filedialog.askopenfilenames(parent=win, title="匯入照片（讀取 EXIF GPS）",
                     filetypes=[("照片", "*.jpg *.jpeg *.png *.webp *.heic *.heif *.bmp")])
        if not paths:
            return
        set_busy(True)
        status.set(f"正在匯入 {len(paths)} 張照片…")

        def finished(report, error):
            set_busy(False)
            refresh()
            if error:
                messagebox.showerror("匯入失敗", error, parent=win)
                status.set("匯入未完成，請查看錯誤訊息。")
                return
            status.set(f"新增 {report['added']} 張（其中 {report['missing_gps']} 張需補座標），重複 {report['duplicates']} 張，失敗 {len(report['errors'])} 張。")
            if report["errors"]:
                messagebox.showwarning("部分照片無法匯入", "\n".join(report["errors"][:12]), parent=win)

        def worker():
            report, error = None, None
            try:
                report = gps.import_photos(paths, folder)
            except Exception as ex:
                error = str(ex)
            win.after(0, lambda: finished(report, error))
        threading.Thread(target=worker, daemon=True).start()

    def selected_one():
        selected = tree.selection()
        if len(selected) != 1:
            messagebox.showinfo("提示", "請先選擇一張照片", parent=win)
            return None
        return next(r for r in records if r["id"] == selected[0])

    def edit():
        record = selected_one()
        if record is None:
            return
        coords = simpledialog.askstring("設定照片座標", "輸入緯度, 經度，例如：46.623, 12.308",
                  initialvalue=f"{record['lat']}, {record['lon']}" if record["lat"] is not None else "", parent=win)
        if coords is None:
            return
        try:
            parts = coords.replace("，", ",").replace(",", " ").split()
            if len(parts) != 2:
                raise ValueError("請輸入兩個數字：緯度, 經度")
            lat, lon = gps.validate_coordinates(*parts)
            updated = [dict(r, lat=lat, lon=lon, source="manual") if r["id"] == record["id"] else r for r in records]
            gps.save_catalog(folder, updated)
            refresh()
        except Exception as ex:
            messagebox.showerror("座標設定失敗", str(ex), parent=win)

    def rename():
        record = selected_one()
        if record is None:
            return
        name = simpledialog.askstring("照片名稱", "影片照片卡片顯示的名稱：", initialvalue=record["name"], parent=win)
        if not name or not name.strip():
            return
        try:
            gps.save_catalog(folder, [dict(r, name=name.strip()) if r["id"] == record["id"] else r for r in records])
            refresh()
        except Exception as ex:
            messagebox.showerror("儲存失敗", str(ex), parent=win)

    def remove():
        selected = set(tree.selection())
        if not selected:
            return
        if not messagebox.askyesno("移除匯入照片", f"從清單移除 {len(selected)} 張照片？\n原始照片不受影響。", parent=win):
            return
        try:
            # Retain managed copies so existing renders and other references stay valid.
            gps.save_catalog(folder, [r for r in records if r["id"] not in selected])
            refresh()
        except Exception as ex:
            messagebox.showerror("移除失敗", str(ex), parent=win)

    def close():
        if busy:
            messagebox.showinfo("匯入中", "請等照片匯入完成後再關閉", parent=win)
        else:
            win.destroy()

    add_button = ttk.Button(buttons, text="＋ 匯入照片", command=add)
    edit_button = ttk.Button(buttons, text="設定／補上 GPS", command=edit)
    rename_button = ttk.Button(buttons, text="修改名稱", command=rename)
    remove_button = ttk.Button(buttons, text="移除選取", command=remove)
    for button in (add_button, edit_button, rename_button, remove_button):
        button.pack(side="left", padx=(0, 8))
    ttk.Button(buttons, text="關閉", command=close).pack(side="right")
    route_combo.bind("<<ComboboxSelected>>", refresh)
    win.protocol("WM_DELETE_WINDOW", close)
    refresh()
