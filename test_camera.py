"""Camera geometry: mountain framing, terrain clearance and route transitions."""
import math
from types import SimpleNamespace
import unittest

import numpy as np

from terrain3d import camera_path


def scene_for(x, y=None, terrain=None):
    x = np.asarray(x, float)
    y = np.zeros_like(x) if y is None else np.asarray(y, float)
    terrain = terrain or (lambda x, y: np.zeros_like(np.asarray(x), dtype=float) + 2000)
    d = np.r_[0, np.cumsum(np.hypot(np.diff(x), np.diff(y)))]
    return SimpleNamespace(tx=x, ty=y, tz=terrain(x, y), ex=1.5,
                           terrain_at=terrain, data={"dists": d / 1000})


def follow(scene, **kwargs):
    s = np.linspace(0, scene.data["dists"][-1] * 1000, 480)
    cam, focal, _, back, overview = camera_path(scene, s, 24, n_outro=48, **kwargs)
    moving = overview == 0
    target = np.stack([np.interp(s, scene.data["dists"] * 1000, a)
                       for a in (scene.tx, scene.ty, scene.tz)], axis=1)
    return cam, focal, back, moving, target, overview


class CameraTests(unittest.TestCase):
    def test_flat_route_follows_from_behind_and_above_with_slight_downward_view(self):
        cam, focal, _, moving, target, _ = follow(scene_for(np.linspace(0, 6000, 301)))
        self.assertTrue(np.all(cam[moving, 0] < target[moving, 0]))
        self.assertTrue(np.all(cam[moving, 2] > target[moving, 2]))
        v = focal - cam
        angle = np.degrees(np.arctan2(v[:, 2], np.linalg.norm(v[:, :2], axis=1)))
        np.testing.assert_allclose(angle[moving], -5, atol=1e-8)

    def test_camera_swings_around_and_changes_height_while_following(self):
        cam, _, _, moving, target, _ = follow(scene_for(np.linspace(0, 6000, 301)))
        rel = cam[moving] - target[moving]
        side = np.degrees(np.arctan2(rel[:, 1], -rel[:, 0]))
        elevation = np.degrees(np.arctan2(rel[:, 2], np.linalg.norm(rel[:, :2], axis=1)))
        self.assertLess(side.min(), -10)
        self.assertGreater(side.max(), 10)
        self.assertLess(np.abs(side).max(), 30)
        self.assertGreater(elevation.min(), 6)
        self.assertLess(elevation.max(), 25)
        self.assertGreater(np.ptp(elevation), 5)
        # 緩慢變化：相鄰幀的方位角變化不超過 1°
        self.assertLess(np.abs(np.diff(side)).max(), 1.0)

    def test_zero_orbit_stays_directly_behind(self):
        cam, _, back, moving, target, _ = follow(scene_for(np.linspace(0, 6000, 301)), orbit=0)
        side = np.degrees(np.arctan2(cam[moving, 1] - target[moving, 1], target[moving, 0] - cam[moving, 0]))
        self.assertLess(np.abs(side).max(), 1.0)

    def test_short_route_keeps_hiker_and_dot_above_the_hud_in_both_formats(self):
        for aspect in (9 / 16, 16 / 9):
            for marker in ('hiker', 'dot'):
                with self.subTest(aspect=aspect, marker=marker):
                    cam, focal, back, moving, target, _ = follow(
                        scene_for(np.linspace(0, 200, 41)), aspect=aspect, marker=marker)
                    # Keep the feet / bottom of the dot clear of the profile, not just its center.
                    if marker == 'dot':
                        target[:, 2] -= max(6, back * 0.022) * 0.2
                    view = focal - cam
                    look = np.arctan2(view[:, 2], np.linalg.norm(view[:, :2], axis=1))
                    v = target - cam
                    actor = np.arctan2(v[:, 2], np.linalg.norm(v[:, :2], axis=1))
                    # VTK window-center shift -0.15 moves the subject upward by 7.5%.
                    screen_y = 0.5 + 0.5 * (np.tan(look - actor) / math.tan(math.radians(25)) - 0.15)
                    self.assertLessEqual(float(screen_y[moving].max()), (0.70 if aspect < 1 else 0.78) + 1e-8)

    def test_ridge_does_not_hide_the_actor_or_intersect_the_camera(self):
        def terrain(x, y):
            return 2000 + 650 * np.exp(-((np.asarray(x) - 2600) / 140) ** 2)
        scene = scene_for(np.linspace(0, 6000, 601), terrain=terrain)
        cam, focal, back, moving, target, _ = follow(scene, aspect=9 / 16)
        self.assertTrue(np.all(cam[moving, 2] > scene.terrain_at(cam[moving, 0], cam[moving, 1])))
        self.assertTrue(np.any(np.linalg.norm(cam[moving, :2] - target[moving, :2], axis=1) < back * 0.9))
        from terrain3d import hiker_size
        target[:, 2] += hiker_size(back)
        ts = np.linspace(0.04, 0.9, 40)
        ray = cam[moving, None, :] * (1 - ts[None, :, None]) + target[moving, None, :] * ts[None, :, None]
        self.assertTrue(np.all(ray[:, :, 2] >= scene.terrain_at(ray[:, :, 0], ray[:, :, 1]) - 1e-6))
        self.assertTrue(np.isfinite(focal).all())

    def test_manual_level_or_downward_angle_is_respected(self):
        scene = scene_for(np.linspace(0, 6000, 301))
        for look_up in (0, -10):
            # 高度低到小人仍在畫面內時，不應自動改動指定的角度
            cam, focal, _, moving, _, _ = follow(scene, look_up=look_up, pitch=0.10)
            v = focal - cam
            angle = np.degrees(np.arctan2(v[:, 2], np.linalg.norm(v[:, :2], axis=1)))
            np.testing.assert_allclose(angle[moving], look_up, atol=1e-8)

    def test_switchback_and_photo_hold_keep_camera_finite_and_smooth(self):
        scene = scene_for([0, 2000, 2000, 0], [0, 0, 100, 100])
        s = np.r_[np.linspace(0, 2000, 240), np.full(180, 2000), np.linspace(2000, 4100, 240)]
        cam, focal, _, _, overview = camera_path(scene, s, 24, n_outro=48)
        self.assertTrue(np.isfinite(cam).all() and np.isfinite(focal).all())
        self.assertLess(float(np.linalg.norm(np.diff(cam[320:340], axis=0), axis=1).max()), 1.0)
        self.assertEqual(overview[0], 1)
        self.assertEqual(overview[-1], 1)
        self.assertTrue(np.all(overview[240:420] == 0))


if __name__ == "__main__":
    unittest.main()
