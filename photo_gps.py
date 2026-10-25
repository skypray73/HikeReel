"""Local photo GPS catalogue and shared point-to-route matching (MIT License)."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import uuid

import numpy as np
from PIL import Image

CATALOG = "gps_photos.json"
ASSETS = "gps_imports"
PHOTO_EXT = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp")
EARTH_RADIUS = 6371000.0


def validate_coordinates(lat, lon):
    lat, lon = float(lat), float(lon)
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("座標必須是有效的緯度（-90～90）、經度（-180～180）")
    return lat, lon


def _coordinate(values, ref, positive, negative, maximum):
    if isinstance(ref, bytes):
        ref = ref.decode("ascii")
    ref = str(ref).strip().upper()
    if ref not in (positive, negative) or len(values) != 3:
        raise ValueError("無效的 GPS 方位或度分秒")
    d, m, s = (float(v) for v in values)
    if not all(math.isfinite(v) for v in (d, m, s)) or not (0 <= d <= maximum and 0 <= m < 60 and 0 <= s < 60):
        raise ValueError("無效的 GPS 度分秒")
    value = d + m / 60 + s / 3600
    return -value if ref == negative else value


def read_photo_gps(path):
    """Return EXIF latitude/longitude, or None when GPS is absent. Never infer location."""
    if Path(path).suffix.lower() in (".heic", ".heif"):
        import pillow_heif
        pillow_heif.register_heif_opener()
    with Image.open(path) as im:
        im.verify()
    with Image.open(path) as im:
        exif = im.getexif()
        if 34853 not in exif:
            return None
        gps = exif.get_ifd(34853)
        if not all(k in gps for k in (1, 2, 3, 4)):
            return None
        lat = _coordinate(gps[2], gps[1], "N", "S", 90)
        lon = _coordinate(gps[4], gps[3], "E", "W", 180)
        return validate_coordinates(lat, lon)


def load_catalog(folder):
    path = Path(folder) / CATALOG
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if data.get("version") != 1 or not isinstance(data.get("photos"), list):
        raise ValueError("不支援的 GPS 照片清單格式")
    for record in data["photos"]:
        if not all(k in record for k in ("id", "name", "file", "sha256", "lat", "lon")):
            raise ValueError("GPS 照片清單缺少欄位")
        asset_path(folder, record)  # Reject paths outside this catalogue.
        if record["lat"] is not None or record["lon"] is not None:
            validate_coordinates(record["lat"], record["lon"])
    return data["photos"]


def save_catalog(folder, records):
    root = Path(folder)
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / (CATALOG + "." + uuid.uuid4().hex + ".tmp")
    try:
        tmp.write_text(json.dumps({"version": 1, "photos": records}, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, root / CATALOG)
    finally:
        tmp.unlink(missing_ok=True)


def asset_path(folder, record):
    root = Path(folder).resolve()
    path = (root / record["file"]).resolve()
    if not path.is_relative_to(root):
        raise ValueError("照片路徑必須位於照片資料夾內")
    return path


def import_photos(paths, folder):
    """Copy originals locally; save missing-GPS photos for manual coordinates. Deduplicate by content."""
    records = load_catalog(folder)
    known = {r["sha256"]: r for r in records}
    report = {"added": 0, "missing_gps": 0, "duplicates": 0, "errors": []}
    target = Path(folder) / ASSETS
    target.mkdir(parents=True, exist_ok=True)
    for src in paths:
        try:
            src = Path(src)
            if src.suffix.lower() not in PHOTO_EXT:
                raise ValueError("不支援的照片格式")
            digest = hashlib.sha256()
            with src.open("rb") as f:
                for block in iter(lambda: f.read(1024 * 1024), b""):
                    digest.update(block)
            digest = digest.hexdigest()
            if digest in known:
                # Restore a missing managed copy when re-importing the original.
                dst = asset_path(folder, known[digest])
                if not dst.is_file():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                report["duplicates"] += 1
                continue
            coords = read_photo_gps(str(src))
            ident = uuid.uuid4().hex
            relative = f"{ASSETS}/{ident}{src.suffix.lower()}"
            shutil.copy2(src, Path(folder) / relative)
            record = dict(id=ident, name=src.stem, file=relative, sha256=digest,
                          lat=coords[0] if coords else None, lon=coords[1] if coords else None,
                          source="exif" if coords else "missing")
            records.append(record)
            known[digest] = record
            report["added"] += 1
            if coords is None:
                report["missing_gps"] += 1
        except Exception as ex:
            report["errors"].append(f"{Path(src).name}：{ex}")
    save_catalog(folder, records)
    return report


def nearest_route_position(lat, lon, lats, lons):
    """Return (fractional GPX index, horizontal offset metres) to the nearest segment.

    Local equirectangular projection is appropriate for hiking routes. Longitude
    wrapping also handles routes crossing the date line; altitude is not used.
    """
    lat, lon = validate_coordinates(lat, lon)
    lats, lons = np.asarray(lats, dtype=float), np.asarray(lons, dtype=float)
    if lats.ndim != 1 or lats.shape != lons.shape or not len(lats):
        raise ValueError("GPX 軌跡必須含有座標")
    if not (np.all(np.isfinite(lats)) and np.all(np.isfinite(lons))):
        raise ValueError("GPX 軌跡含有無效座標")
    x = np.radians((lons - lon + 180) % 360 - 180) * EARTH_RADIUS * max(abs(math.cos(math.radians(lat))), 1e-9)
    y = np.radians(lats - lat) * EARTH_RADIUS
    points = np.column_stack((x, y))
    if len(points) == 1:
        return 0.0, float(np.linalg.norm(points[0]))
    a, v = points[:-1], np.diff(points, axis=0)
    vv = np.einsum("ij,ij->i", v, v)
    t = np.clip(np.divide(-np.einsum("ij,ij->i", a, v), vv, out=np.zeros_like(vv), where=vv > 0), 0, 1)
    nearest = a + t[:, None] * v
    dist2 = np.einsum("ij,ij->i", nearest, nearest)
    i = int(np.argmin(dist2))  # Equally close return routes use the first occurrence.
    return float(i + t[i]), float(math.sqrt(dist2[i]))


def match_photos(folder, lats, lons, radius_km=0.5, log=print):
    """Return imported photos on this route only, in route order; keep multiple photos at one spot."""
    if not math.isfinite(radius_km) or radius_km < 0:
        raise ValueError("篩選半徑必須是大於或等於 0 的公里數")
    matches = []
    for record in load_catalog(folder):
        name = record["name"]
        if record["lat"] is None or record["lon"] is None:
            log(f"   ⚠️ GPS 照片略過（尚未設定座標）：{name}")
            continue
        path = asset_path(folder, record)
        if not path.is_file():
            log(f"   ⚠️ GPS 照片檔案遺失：{name}")
            continue
        near, offset = nearest_route_position(record["lat"], record["lon"], lats, lons)
        if offset <= radius_km * 1000 + 1e-6:
            matches.append(dict(record, path=str(path), near=near, offset_m=offset))
        else:
            log(f"   GPS 照片略過（離軌跡 {offset:.0f} m，超過 {radius_km * 1000:g} m）：{name}")
    matches.sort(key=lambda r: r["near"])
    if matches:
        log(f"   🖼️ GPS 照片：{len(matches)} 張（篩選半徑 {radius_km * 1000:g} m）")
    return matches
