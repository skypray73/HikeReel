"""Regression coverage for EXIF import, route matching and photo timing."""
import csv
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageFont
from PIL.TiffImagePlugin import IFDRational

import photo_gps as gps
from landmark_photos import PhotoCard, build_schedule


def make_photo(path, lat=None, lon=None):
    exif = Image.Exif()
    if lat is not None:
        def dms(value):
            value = abs(value)
            d = int(value)
            m = int((value - d) * 60)
            s = (value - d - m / 60) * 3600
            return (IFDRational(d), IFDRational(m), IFDRational(s))
        exif[34853] = {1: "N" if lat >= 0 else "S", 2: dms(lat),
                       3: "E" if lon >= 0 else "W", 4: dms(lon)}
    Image.new("RGB", (80, 60), "orange").save(path, exif=exif)


class PhotoGpsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / "照片"

    def tearDown(self):
        self.temp.cleanup()

    def test_real_exif_north_east_and_south_west(self):
        for lat, lon in ((46.62345, 12.30876), (-25.0478, -121.5319), (0, 0)):
            path = self.root / "定位.jpg"
            make_photo(path, lat, lon)
            actual = gps.read_photo_gps(path)
            self.assertAlmostEqual(actual[0], lat, places=7)
            self.assertAlmostEqual(actual[1], lon, places=7)

    def test_no_gps_is_not_inferred(self):
        path = self.root / "無定位.png"
        make_photo(path)
        self.assertIsNone(gps.read_photo_gps(path))
        report = gps.import_photos([path], self.folder)
        self.assertEqual(report["missing_gps"], 1)
        self.assertEqual(gps.match_photos(self.folder, [46, 47], [12, 12], log=lambda _: None), [])

    def test_new_import_has_no_video_caption(self):
        path = self.root / "IMG_1234.jpg"
        make_photo(path, 46.62, 12.3)
        gps.import_photos([path], self.folder)
        record = gps.load_catalog(self.folder)[0]
        self.assertEqual(record["name"], "IMG_1234")
        self.assertEqual(record["caption"], "")
        match = gps.match_photos(self.folder, [46.61, 46.63], [12.3, 12.3], log=lambda _: None)[0]
        self.assertEqual(match["caption"], "")

    def test_v210_catalogue_never_uses_filename_as_caption(self):
        path = self.root / "IMG_5678.jpg"
        make_photo(path, 46.62, 12.3)
        gps.import_photos([path], self.folder)
        records = gps.load_catalog(self.folder)
        del records[0]["caption"]
        gps.save_catalog(self.folder, records)
        match = gps.match_photos(self.folder, [46.61, 46.63], [12.3, 12.3], log=lambda _: None)[0]
        self.assertEqual(match["name"], "IMG_5678")
        self.assertEqual(match["caption"], "")

    def test_optional_caption_can_be_saved_and_cleared(self):
        path = self.root / "IMG_1234.jpg"
        make_photo(path, 46.62, 12.3)
        gps.import_photos([path], self.folder)
        records = gps.load_catalog(self.folder)
        for caption in ("三尖峰北壁", ""):
            records[0]["caption"] = caption
            gps.save_catalog(self.folder, records)
            match = gps.match_photos(self.folder, [46.61, 46.63], [12.3, 12.3], log=lambda _: None)[0]
            self.assertEqual(match["caption"], caption)
            self.assertEqual(match["name"], "IMG_1234")

    def test_card_without_caption_omits_dark_title_bar(self):
        path = self.root / "image.jpg"
        make_photo(path)
        frame = np.full((640, 360, 3), (40, 80, 120), dtype=np.uint8)
        font = ImageFont.load_default(size=18)
        for caption in ("", "   ", None):
            card = PhotoCard(str(path), caption, 360, 640, .5, font)
            self.assertEqual(card.lines, [])
            result = card.draw(frame, .5, 1)
            navy = np.all(result == (15, 20, 40), axis=2)
            self.assertEqual(np.count_nonzero(navy), 0)

    def test_excel_landmark_caption_still_renders(self):
        path = self.root / "image.jpg"
        make_photo(path)
        font = ImageFont.load_default(size=18)
        card = PhotoCard(str(path), "Landmark\nRifugio", 360, 640, .5, font)
        self.assertEqual(card.lines, ["Landmark", "Rifugio"])
        result = card.draw(np.zeros((640, 360, 3), dtype=np.uint8), .5, 1)
        self.assertGreater(np.count_nonzero(np.all(result == (15, 20, 40), axis=2)), 100)

    def test_import_copies_and_deduplicates_and_restores_missing_copy(self):
        path = self.root / "三尖峰.jpg"
        make_photo(path, 46.62, 12.3)
        original = path.read_bytes()
        report = gps.import_photos([path, path], self.folder)
        self.assertEqual((report["added"], report["duplicates"]), (1, 1))
        records = gps.load_catalog(self.folder)
        copy = gps.asset_path(self.folder, records[0])
        self.assertEqual(copy.read_bytes(), original)
        copy.unlink()
        self.assertEqual(gps.import_photos([path], self.folder)["duplicates"], 1)
        self.assertEqual(copy.read_bytes(), original)
        self.assertEqual(path.read_bytes(), original)

    def test_manual_coordinates_persist_and_repeated_spot_keeps_both(self):
        first, second = self.root / "one.jpg", self.root / "two.jpg"
        make_photo(first)
        make_photo(second, 46.62, 12.3)
        gps.import_photos([first, second], self.folder)
        records = gps.load_catalog(self.folder)
        records[0].update(lat=46.62, lon=12.3, source="manual", name="手動座標")
        gps.save_catalog(self.folder, records)
        matches = gps.match_photos(self.folder, [46.61, 46.63], [12.3, 12.3], log=lambda _: None)
        self.assertEqual(len(matches), 2)
        self.assertAlmostEqual(matches[0]["near"], .5, places=6)
        self.assertEqual(matches[0]["name"], "手動座標")

    def test_invalid_and_unsupported_images_reported(self):
        bad = self.root / "broken.jpg"
        bad.write_bytes(b"not an image")
        unsupported = self.root / "not-a-photo.txt"
        unsupported.write_text("data")
        report = gps.import_photos([bad, unsupported], self.folder)
        self.assertEqual(len(report["errors"]), 2)
        self.assertEqual(report["added"], 0)

    def test_sparse_route_midpoint_and_500_metre_boundary(self):
        lat = math.degrees(500 / gps.EARTH_RADIUS)
        index, distance = gps.nearest_route_position(lat, 0, [0, 0], [-.02, .02])
        self.assertAlmostEqual(index, .5, places=6)
        self.assertAlmostEqual(distance, 500, places=5)
        path = self.root / "edge.jpg"
        make_photo(path, lat, 0)
        gps.import_photos([path], self.folder)
        self.assertEqual(len(gps.match_photos(self.folder, [0, 0], [-.02, .02], .5, log=lambda _: None)), 1)
        self.assertEqual(len(gps.match_photos(self.folder, [0, 0], [-.02, .02], .499, log=lambda _: None)), 0)

    def test_high_latitude_longitude_and_date_line(self):
        lon_offset = math.degrees(400 / (gps.EARTH_RADIUS * math.cos(math.radians(60))))
        _, distance = gps.nearest_route_position(60, lon_offset, [59.99, 60.01], [0, 0])
        self.assertAlmostEqual(distance, 400, places=4)
        index, distance = gps.nearest_route_position(0, 180, [0, 0], [179.99, -179.99])
        self.assertAlmostEqual(index, .5)
        self.assertAlmostEqual(distance, 0)

    def test_duplicate_vertices_single_point_and_return_route(self):
        self.assertEqual(gps.nearest_route_position(0, 0, [0], [0]), (0.0, 0.0))
        self.assertEqual(gps.nearest_route_position(0, 0, [0, 0], [0, 0]), (0.0, 0.0))
        index, _ = gps.nearest_route_position(0, .01, [0, 0, 0], [0, .02, 0])
        self.assertAlmostEqual(index, .5)  # Ambiguous return routes use first visit.

    def test_invalid_coordinates_and_radius(self):
        for lat, lon in ((float("nan"), 1), (91, 0), (0, float("inf")), (0, 181)):
            with self.assertRaises(ValueError):
                gps.validate_coordinates(lat, lon)
        for radius in (-1, float("nan")):
            with self.assertRaises(ValueError):
                gps.match_photos(self.folder, [0], [0], radius)

    def test_catalog_rejects_external_photo_paths(self):
        path = self.root / "photo.jpg"
        make_photo(path, 0, 0)
        gps.import_photos([path], self.folder)
        records = gps.load_catalog(self.folder)
        records[0]["file"] = "../../outside.jpg"
        gps.save_catalog(self.folder, records)
        with self.assertRaises(ValueError):
            gps.load_catalog(self.folder)

    def test_schedule_allows_multiple_photos_and_endpoint(self):
        s, ranges = build_schedule(100, 11, [(50, 3, "a"), (50, 3, "b"), (100, 3, "end")])
        self.assertEqual(len(s), 20)
        self.assertTrue(np.all(np.diff(s) >= 0))
        self.assertEqual([r[2] for r in ranges], ["a", "b", "end"])
        for a, b, name in ranges:
            self.assertTrue(np.all(s[a:b] == (100 if name == "end" else 50)))

    def test_excel_and_csv_use_same_segment_distance(self):
        import openpyxl
        from gpx_to_video import load_landmarks
        rows = [["名稱", "緯度", "經度"], ["midpoint", .001, 0], ["outside", .01, 0]]
        csv_path = self.root / "landmarks.csv"
        with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerows(rows)
        xlsx_path = self.root / "landmarks.xlsx"
        wb = openpyxl.Workbook()
        for row in rows:
            wb.active.append(row)
        wb.save(xlsx_path)
        for path in (csv_path, xlsx_path):
            selected = load_landmarks(str(path), .5, np.array([0, 0]), np.array([-.02, .02]))
            self.assertEqual([r[0] for r in selected], ["midpoint"])


if __name__ == "__main__":
    unittest.main()
