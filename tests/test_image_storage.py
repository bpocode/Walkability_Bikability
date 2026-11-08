import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import master


def response(data=None, status=200):
    result = Mock(status_code=status, content=b'jpeg', headers={'Content-Type': 'image/jpeg'})
    result.json.return_value = data
    return result


class ImageStorageTests(unittest.TestCase):
    def test_mode_spacing_and_explicit_override(self):
        route = [(35, -120), (35.01, -120)]
        for mode, spacing in [("WALK", 100), ("BICYCLE", 150)]:
            points = master.get_image_points(route, travel_mode=mode)
            intervals = [p for p in points if p["selection_reason"] == "interval"]
            self.assertGreater(len(intervals), 2)
            self.assertAlmostEqual(intervals[0]["distance_along_route_meters"],
                                   spacing * 0.3048, delta=0.01)
            self.assertAlmostEqual(intervals[1]["distance_along_route_meters"] -
                                   intervals[0]["distance_along_route_meters"],
                                   spacing * 0.3048, delta=0.01)
        points = master.get_image_points(route, spacing_feet=200, travel_mode="WALK")
        self.assertAlmostEqual(points[1]["distance_along_route_meters"], 60.96)

    def test_mode_heading_offsets(self):
        for mode, offset in [("WALK", 40), ("BICYCLE", 15)]:
            points = master.get_image_points([(35, -120), (35.001, -120)], travel_mode=mode)
            for point in points:
                self.assertAlmostEqual(point["camera_heading"], (point["route_heading"] + offset) % 360, places=2)

    def test_filename_wraps_and_preserves_precision(self):
        self.assertEqual(master.streetview_filename(35.24653, -120.642063, 474.574, '2025-09'),
                         'sv_lat35.246530_lon-120.642063_h114.574_2025-09.jpg')
        self.assertIn('_h0.000_', master.streetview_filename(1, 2, 359.9999, '2025-09'))

    def test_saved_missing_and_cache(self):
        points = [dict(latitude=35.2, longitude=-120.6, camera_heading=114.574),
                  dict(latitude=35.3, longitude=-120.7, camera_heading=10)]
        metadata = {'status': 'OK', 'location': {'lat': 35.20001, 'lng': -120.60002},
                    'date': '2025-09', 'pano_id': 'panorama'}
        with tempfile.TemporaryDirectory() as folder, patch.object(master.requests, 'get') as get:
            get.side_effect = [response(metadata), response(), response({'status': 'ZERO_RESULTS'})]
            paths = master.get_images(points, output_folder=folder, api_key='test')
            self.assertEqual(len(paths), 1)
            self.assertTrue(paths[0].is_file())
            self.assertEqual(points[0]['image_filename'], paths[0].name)
            self.assertEqual(points[0]['image_latitude'], 35.20001)
            self.assertEqual(points[1]['status'], 'unavailable')
            self.assertIsNone(points[1]['image_filename'])
            self.assertEqual(json.loads((Path(folder)/'point_images.json').read_text()), points)
            self.assertEqual(get.call_args_list[1].kwargs['params']['pano'], 'panorama')
            get.reset_mock()
            master.get_images(points[:1], output_folder=folder, api_key='test')
            get.assert_not_called()

    def test_404_and_missing_date_return_no_image(self):
        for replies, status in [([response({'status': 'OK', 'location': {'lat': 1, 'lng': 2},
                                          'date': '2025-09', 'pano_id': 'p'}), response(status=404)], 'unavailable'),
                                ([response({'status': 'OK', 'location': {'lat': 1, 'lng': 2},
                                            'pano_id': 'p'})], 'capture_date_unavailable')]:
            point = dict(latitude=1, longitude=2)
            with tempfile.TemporaryDirectory() as folder, patch.object(master.requests, 'get', side_effect=replies):
                self.assertEqual(master.get_images([point], output_folder=folder, api_key='test'), [])
                self.assertEqual(point['status'], status)
                self.assertIsNone(point['image_filename'])

    def test_route_json_preserves_missing_point(self):
        data = dict(photo_folder='Walking Photos', route_id='R001', travel_mode='WALK',
                    image_points=[dict(location_index=0, latitude=1, longitude=2)])
        with tempfile.TemporaryDirectory() as folder, patch.object(master.requests, 'get', return_value=response({'status': 'ZERO_RESULTS'})), patch.object(master, '_api_key', return_value='test'):
            master.save_route_images(data, base=folder)
            saved = json.loads((Path(folder)/'Walking Photos/R001/route_points.json').read_text())
            self.assertEqual(saved['image_points'][0]['status'], 'unavailable')
            self.assertIsNone(saved['image_points'][0]['image_filename'])


if __name__ == '__main__':
    unittest.main()
