"""Three steps: get_route -> get_image_points -> get_images.

Coordinates always use (latitude, longitude). Nothing runs on import.
Paste GOOGLE_MAPS_API_KEY into the adjacent .env file, or pass api_key explicitly.
"""

import os
import json
import csv
import re
from math import asin, atan2, cos, degrees, radians, sin, sqrt
from pathlib import Path

import requests
from dotenv import load_dotenv


def _api_key(api_key):
    load_dotenv(Path(__file__).with_name(".env"))
    key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        raise ValueError("Pass api_key or set GOOGLE_MAPS_API_KEY.")
    return key


def get_route(origin, destination, travel_mode="WALK", api_key=None):
    """Return route coordinates between two (latitude, longitude) points.

    travel_mode is "WALK" or "BICYCLE". Requires Google Routes API access.
    """
    travel_mode = travel_mode.upper()
    if travel_mode not in {"WALK", "BICYCLE"}:
        raise ValueError('travel_mode must be "WALK" or "BICYCLE".')

    def waypoint(point):
        return {"location": {"latLng": {
            "latitude": point[0], "longitude": point[1],
        }}}

    response = requests.post(
        "https://routes.googleapis.com/directions/v2:computeRoutes",
        headers={
            "X-Goog-Api-Key": _api_key(api_key),
            "X-Goog-FieldMask": "routes.polyline.geoJsonLinestring",
        },
        json={
            "origin": waypoint(origin),
            "destination": waypoint(destination),
            "travelMode": travel_mode,
            "polylineQuality": "HIGH_QUALITY",
            "polylineEncoding": "GEO_JSON_LINESTRING",
        },
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(f"Google Routes request failed (HTTP {response.status_code}).")
    routes = response.json().get("routes", [])
    if not routes:
        raise ValueError("Google did not return a route for these endpoints.")
    coordinates = routes[0]["polyline"]["geoJsonLinestring"]["coordinates"]
    # Google GeoJSON puts longitude first; our functions put latitude first.
    return [(latitude, longitude) for longitude, latitude in coordinates]


def heading_offset(travel_mode):
    """Camera offset clockwise from travel direction, by transportation mode."""
    mode = travel_mode.upper()
    if mode not in {"WALK", "BICYCLE"}:
        raise ValueError('travel_mode must be "WALK" or "BICYCLE".')
    return 40 if mode == "WALK" else 15


def image_spacing_feet(travel_mode):
    """Default distance along the route between image selections, in feet."""
    heading_offset(travel_mode)  # Validate the same supported transportation modes.
    return 100 if travel_mode.upper() == "WALK" else 150


def get_image_points(
    route_points,
    spacing_feet=None,
    turn_threshold_degrees=30,
    heading_offset_degrees=None,
    travel_mode="WALK",
):
    """Return evenly spaced and turn-aware Street View request locations.

    Defaults to 100-foot walking or 150-foot biking spacing, with a
    40-degree walking or 15-degree biking camera offset.
    Every returned dictionary includes its distance along the route, route and
    camera headings, and a reason describing why the location was selected.
    """
    if spacing_feet is None:
        spacing_feet = image_spacing_feet(travel_mode)
    if heading_offset_degrees is None:
        heading_offset_degrees = heading_offset(travel_mode)
    if not route_points:
        raise ValueError("At least one route point is required.")
    if spacing_feet <= 0:
        raise ValueError("spacing_feet must be greater than zero.")
    if turn_threshold_degrees < 0 or turn_threshold_degrees > 180:
        raise ValueError("turn_threshold_degrees must be between 0 and 180.")

    points = [tuple(map(float, point)) for point in route_points]
    if len(points) == 1:
        return [
            {
                "location_index": 0,
                "latitude": points[0][0],
                "longitude": points[0][1],
                "distance_along_route_meters": 0.0,
                "route_heading": 0.0,
                "camera_heading": heading_offset_degrees % 360,
                "selection_reason": "origin+destination",
            }
        ]

    segment_lengths = [
        calculate_distance_meters(points[index], points[index + 1])
        for index in range(len(points) - 1)
    ]
    cumulative_distances = [0.0]
    for segment_length in segment_lengths:
        cumulative_distances.append(cumulative_distances[-1] + segment_length)
    total_distance = cumulative_distances[-1]

    def location_at_distance(target_distance):
        target = min(max(float(target_distance), 0.0), total_distance)
        for index, segment_end in enumerate(cumulative_distances[1:]):
            if target <= segment_end or index == len(segment_lengths) - 1:
                segment_start = cumulative_distances[index]
                segment_length = segment_lengths[index]
                fraction = 0.0 if segment_length == 0 else (
                    (target - segment_start) / segment_length
                )
                start = points[index]
                end = points[index + 1]
                latitude = start[0] + fraction * (end[0] - start[0])
                longitude = start[1] + fraction * (end[1] - start[1])
                return (
                    latitude,
                    longitude,
                    calculate_heading(start, end),
                )
        return points[-1][0], points[-1][1], calculate_heading(points[-2], points[-1])

    candidates = []
    spacing_meters = spacing_feet * 0.3048
    target_distance = 0.0
    while target_distance < total_distance:
        latitude, longitude, route_heading = location_at_distance(target_distance)
        reason = "origin" if target_distance == 0 else "interval"
        candidates.append(
            {
                "latitude": latitude,
                "longitude": longitude,
                "distance_along_route_meters": target_distance,
                "route_heading": route_heading,
                "selection_reason": reason,
            }
        )
        target_distance += spacing_meters

    final_heading = calculate_heading(points[-2], points[-1])
    candidates.append(
        {
            "latitude": points[-1][0],
            "longitude": points[-1][1],
            "distance_along_route_meters": total_distance,
            "route_heading": final_heading,
            "selection_reason": "destination",
        }
    )

    for index in range(1, len(points) - 1):
        incoming_heading = calculate_heading(points[index - 1], points[index])
        outgoing_heading = calculate_heading(points[index], points[index + 1])
        if _heading_difference(incoming_heading, outgoing_heading) >= turn_threshold_degrees:
            candidates.append(
                {
                    "latitude": points[index][0],
                    "longitude": points[index][1],
                    "distance_along_route_meters": cumulative_distances[index],
                    "route_heading": outgoing_heading,
                    "selection_reason": "turn",
                }
            )

    # Merge selections that land within one meter of each other. This commonly
    # happens when a regular interval falls directly on a turn or endpoint.
    candidates.sort(key=lambda item: item["distance_along_route_meters"])
    selected = []
    for candidate in candidates:
        if selected and calculate_distance_meters(
            (selected[-1]["latitude"], selected[-1]["longitude"]),
            (candidate["latitude"], candidate["longitude"]),
        ) < 1:
            reasons = selected[-1]["selection_reason"].split("+")
            if candidate["selection_reason"] not in reasons:
                selected[-1]["selection_reason"] += f"+{candidate['selection_reason']}"
            if candidate["selection_reason"] == "turn":
                selected[-1]["route_heading"] = candidate["route_heading"]
            continue
        selected.append(candidate)

    for location_index, location in enumerate(selected):
        location["location_index"] = location_index
        location["camera_heading"] = round(
            (location["route_heading"] + heading_offset_degrees) % 360,
            2,
        )
        location["distance_along_route_meters"] = round(
            location["distance_along_route_meters"],
            2,
        )
    return selected


def find_nearest_image(point, api_key=None, search_radii=(100, 200, 500)):
    """Find the closest outdoor panorama, expanding the search in meters.

    Returns panorama coordinates/ID and distance from the requested point,
    or None when no coverage is found within the largest radius.
    This searches geographically; the panorama may be on another street.
    """
    key = _api_key(api_key)
    latitude, longitude = point
    radii = sorted(set(search_radii))
    if not radii or any(radius <= 0 for radius in radii):
        raise ValueError("search_radii must contain positive distances in meters.")
    for radius in radii:
        response = requests.get(
            "https://maps.googleapis.com/maps/api/streetview/metadata",
            params={"location": f"{latitude},{longitude}", "radius": radius,
                    "source": "outdoor", "key": key},
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError(f"Street View metadata failed (HTTP {response.status_code}).")
        data = response.json()
        if data.get("status") == "ZERO_RESULTS":
            continue
        if data.get("status") != "OK":
            raise RuntimeError(f"Street View metadata failed: {data.get('status', 'UNKNOWN')}.")
        location = data["location"]
        distance = calculate_distance_meters(point, (location["lat"], location["lng"]))
        if distance > radius:
            continue
        return {
            "panorama_id": data["pano_id"],
            "image_latitude": location["lat"],
            "image_longitude": location["lng"],
            "image_offset_meters": round(distance, 2),
            "search_radius_meters": radius,
        }
    return None


def streetview_filename(latitude, longitude, heading, capture_month):
    """Use panorama coordinates, normalized camera heading, and capture month."""
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", capture_month):
        raise ValueError("Street View capture month must be YYYY-MM.")
    normalized = round(heading % 360, 3) % 360
    return f"sv_lat{latitude:.6f}_lon{longitude:.6f}_h{normalized:.3f}_{capture_month}.jpg"


def get_images(points, pitch=-5, output_folder="route_images", api_key=None,
               fallback_radii=(), travel_mode="WALK"):
    """Return only saved image paths; persist every point in point_images.json.

    Missing coverage has status 'unavailable' and image_filename null. No wider
    fallback search is performed. Dictionaries are updated in place for route
    JSON storage. The compatibility argument fallback_radii must stay empty.
    """
    if fallback_radii:
        raise ValueError("Nearby-image fallback is disabled; leave fallback_radii empty.")
    if not -90 <= pitch <= 90:
        raise ValueError("pitch must be between -90 and 90 degrees.")
    offset = heading_offset(travel_mode)
    points = list(points)
    if not points:
        return []
    key = _api_key(api_key)
    folder = Path(output_folder)
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder / "point_images.json"
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    coordinates = [
        (p["latitude"], p["longitude"]) if isinstance(p, dict) else tuple(p)
        for p in points
    ]
    records = []
    saved_images = []
    try:
        for index, point in enumerate(points):
            latitude, longitude = coordinates[index]
            if isinstance(point, dict) and "camera_heading" in point:
                heading = point["camera_heading"]
            elif len(coordinates) == 1:
                heading = offset
            elif index < len(coordinates) - 1:
                heading = calculate_heading(coordinates[index], coordinates[index + 1]) + offset
            else:
                heading = calculate_heading(coordinates[index - 1], coordinates[index]) + offset
            heading = round(heading % 360, 3) % 360
            record = point if isinstance(point, dict) else {
                "location_index": index, "latitude": latitude, "longitude": longitude,
            }
            cached = next((r for r in previous if
                r.get("latitude") == latitude and r.get("longitude") == longitude
                and r.get("camera_heading") == heading and r.get("pitch") == pitch
                and r.get("status") == "saved"), None)
            if cached and cached.get("image_filename"):
                path = folder / cached["image_filename"]
                if path.is_file() and path.stat().st_size:
                    record.update(cached)
                    records.append(record)
                    saved_images.append(path)
                    continue
            record.update(camera_heading=heading, pitch=pitch, status="pending",
                          image_filename=None, image_latitude=None, image_longitude=None,
                          capture_month=None, panorama_id=None, image_offset_meters=None)
            record.pop("image_error", None)
            records.append(record)
            try:
                metadata = requests.get(
                    "https://maps.googleapis.com/maps/api/streetview/metadata",
                    params={"location": f"{latitude},{longitude}", "radius": 50,
                            "source": "outdoor", "key": key}, timeout=30,
                )
                metadata.raise_for_status()
                info = metadata.json()
                if info.get("status") == "ZERO_RESULTS":
                    record["status"] = "unavailable"
                    continue
                if info.get("status") != "OK":
                    raise RuntimeError(f"Street View metadata failed: {info.get('status', 'UNKNOWN')}.")
                location = info["location"]
                month = info.get("date")
                if not month or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
                    record["status"] = "capture_date_unavailable"
                    continue
                filename = streetview_filename(location["lat"], location["lng"], heading, month)
                path = folder / filename
                # The filename omits pitch. Reuse only when stored settings match;
                # otherwise replace the file with the newly requested camera view.
                reusable = any(r.get("image_filename") == filename and
                               r.get("pitch") == pitch and r.get("status") == "saved"
                               for r in previous + records[:-1])
                if not (reusable and path.is_file() and path.stat().st_size):
                    response = requests.get(
                        "https://maps.googleapis.com/maps/api/streetview",
                        params={"pano": info["pano_id"], "heading": heading,
                                "pitch": pitch, "size": "600x400", "fov": 100,
                                "return_error_code": "true", "key": key}, timeout=30,
                    )
                    if response.status_code == 404:
                        record["status"] = "unavailable"
                        continue
                    response.raise_for_status()
                    if not response.headers.get("Content-Type", "").lower().startswith("image/"):
                        raise RuntimeError(f"Street View did not return an image for point {index}.")
                    path.write_bytes(response.content)
                record.update(status="saved", image_filename=filename,
                              image_latitude=location["lat"], image_longitude=location["lng"],
                              capture_month=month, panorama_id=info["pano_id"],
                              image_offset_meters=round(calculate_distance_meters(
                                  (latitude, longitude), (location["lat"], location["lng"])), 2))
                saved_images.append(path)
            except Exception as error:
                record.update(status="error", image_filename=None,
                              image_error=type(error).__name__)
                raise
    finally:
        manifest_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return saved_images


def calculate_heading(start, end):
    """Calculate the compass bearing from one route point to the next."""
    latitude_1, longitude_1 = map(radians, start)
    latitude_2, longitude_2 = map(radians, end)
    longitude_change = longitude_2 - longitude_1

    x = sin(longitude_change) * cos(latitude_2)
    y = (
        cos(latitude_1) * sin(latitude_2)
        - sin(latitude_1) * cos(latitude_2) * cos(longitude_change)
    )
    return (degrees(atan2(x, y)) + 360) % 360

def calculate_distance_meters(start, end):
    """Calculate great-circle distance between two latitude/longitude points."""
    earth_radius_meters = 6_371_008.8
    latitude_1, longitude_1 = map(radians, start)
    latitude_2, longitude_2 = map(radians, end)
    latitude_change = latitude_2 - latitude_1
    longitude_change = longitude_2 - longitude_1

    haversine = (
        sin(latitude_change / 2) ** 2
        + cos(latitude_1) * cos(latitude_2) * sin(longitude_change / 2) ** 2
    )
    return 2 * earth_radius_meters * asin(sqrt(haversine))

def _heading_difference(first, second):
    """Return the smallest difference between two compass headings."""
    return abs((float(first) - float(second) + 180) % 360 - 180)


def add_elevations(points, api_key=None):
    """Return point dictionaries with elevation and resolution in meters added."""
    points = [dict(point) for point in points]
    key = _api_key(api_key)
    for start in range(0, len(points), 200):
        batch = points[start:start + 200]
        response = requests.get(
            "https://maps.googleapis.com/maps/api/elevation/json",
            params={
                "locations": "|".join(f"{p['latitude']:.6f},{p['longitude']:.6f}" for p in batch),
                "key": key,
            },
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError(f"Elevation request failed (HTTP {response.status_code}).")
        data = response.json()
        if data.get("status") != "OK":
            raise RuntimeError(f"Elevation request failed: {data.get('status', 'UNKNOWN')}.")
        results = data.get("results", [])
        if len(results) != len(batch):
            raise RuntimeError("Google returned a different number of elevations than requested.")
        for point, result in zip(batch, results):
            point["elevation_meters"] = round(float(result["elevation"]), 2)
            point["elevation_resolution_meters"] = result.get("resolution")
    return points


def read_routes(base="."):
    """Read and validate both CSVs before making API calls."""
    base = Path(base)
    routes = []
    for mode, filename, photo_folder in [
        ("WALK", "origins_and_destinations_walking.csv", "Walking Photos"),
        ("BICYCLE", "origins_and_destinations_biking.csv", "Biking Photos"),
    ]:
        seen = set()
        with (base / "Test Routes" / filename).open(encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                name = row["route_id"].strip()
                if not re.fullmatch(r"[A-Za-z0-9_-]+", name) or name in seen:
                    raise ValueError(f"Invalid or duplicate route_id in {filename}: {name}")
                seen.add(name)
                origin = [float(row["origin_latitude"]), float(row["origin_longitude"])]
                destination = [float(row["destination_latitude"]), float(row["destination_longitude"])]
                for lat, lon in [origin, destination]:
                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        raise ValueError(f"Invalid coordinates in {filename}: {name}")
                routes.append({
                    "route_id": name, "travel_mode": mode,
                    "neighborhood": row["neighborhood"],
                    "destination_name": row["destination_name"],
                    "origin": origin, "destination": destination,
                    "photo_folder": photo_folder,
                })
    return routes


def get_route_data(route, base=".", refresh=False):
    """Get and save a route, its mode-specific interval/turn points, and elevations. Reuse saved data."""
    folder = Path(base) / route["photo_folder"] / route["route_id"]
    folder.mkdir(parents=True, exist_ok=True)
    json_path = folder / "route_points.json"
    settings = {
        "origin": route["origin"], "destination": route["destination"],
        "travel_mode": route["travel_mode"],
        "spacing_feet": image_spacing_feet(route["travel_mode"]),
        "turn_threshold_degrees": 30, "heading_offset_degrees": heading_offset(route["travel_mode"]),
    }
    data = json.loads(json_path.read_text()) if json_path.exists() else {}
    if refresh or data.get("settings") != settings:
        geometry = get_route(route["origin"], route["destination"], route["travel_mode"])
        points = get_image_points(geometry, travel_mode=route["travel_mode"])
        data = {"settings": settings, "route_points": geometry, "image_points": points}
    data.update(route)
    # Saving before the next API step lets a later run reuse completed work.
    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    if any(p.get("elevation_meters") is None for p in data["image_points"]):
        data["image_points"] = add_elevations(data["image_points"])
        json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    return data



def save_route_images(data, pitch=-5, base="."):
    """Save photos, coordinate-to-image CSV, and updated route JSON."""
    folder = Path(base) / data["photo_folder"] / data["route_id"]
    folder.mkdir(parents=True, exist_ok=True)
    json_path = folder / "route_points.json"
    try:
        paths = get_images(data["image_points"], pitch=pitch, output_folder=folder,
                           travel_mode=data["travel_mode"])
    finally:
        # Persist point statuses even if a later request fails.
        data["pitch"] = pitch
        json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    fields = ["location_index", "latitude", "longitude", "elevation_meters",
              "elevation_resolution_meters", "distance_along_route_meters",
              "selection_reason", "camera_heading", "pitch", "image_filename", "status",
              "image_latitude", "image_longitude", "image_offset_meters", "panorama_id",
              "capture_month"]
    with (folder / "point_images.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for point in data["image_points"]:
            writer.writerow({key: point.get(key) for key in fields})
    data["pitch"] = pitch
    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"{data['travel_mode']} {data['route_id']}: {len(data['image_points'])} points, {len(paths)} photos")
    return data


def plot_routes(travel_mode, base=".", point_zoom=15):
    """Plot colored routes with a selector to isolate overlapping paths."""
    import colorsys
    import html
    import folium
    from branca.element import MacroElement, Template

    base = Path(base)
    title = "Walking routes" if travel_mode == "WALK" else "Biking routes"
    map_filename = "walking_routes_map.html" if travel_mode == "WALK" else "biking_routes_map.html"
    photo_folder = "Walking Photos" if travel_mode == "WALK" else "Biking Photos"
    route_map = folium.Map(location=[35.27, -120.66], zoom_start=12, tiles="CartoDB positron")
    folium.map.CustomPane("route-photo-points", z_index=625).add_to(route_map)
    route_map.get_root().header.add_child(folium.Element(
        "<style>.leaflet-route-photo-points-pane { display: none; }</style>"
    ))
    bounds = []
    layers = []
    point_layers = []
    expected = [r for r in read_routes(base) if r["travel_mode"] == travel_mode]
    for index, route in enumerate(expected):
        path = base / photo_folder / route["route_id"] / "route_points.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        if any(data.get(key) != route[key] for key in ["origin", "destination", "travel_mode"]):
            continue
        # Golden-angle hues keep consecutive routes visually different.
        rgb = colorsys.hsv_to_rgb((index * 0.618034) % 1, 0.8, 0.72)
        color = "#" + "".join(f"{round(channel * 255):02x}" for channel in rgb)
        label = f"{data['route_id']} — {data['destination_name']}"
        safe_label = html.escape(label)
        layer = folium.FeatureGroup(name=f'<span style="color:{color}">●</span> {safe_label}')
        # A light outline helps distinguish crossing routes against the basemap.
        folium.PolyLine(data["route_points"], color="white", weight=8,
                        opacity=0.9, interactive=False).add_to(layer)
        folium.PolyLine(data["route_points"], color=color, weight=4,
                        opacity=0.9, tooltip=safe_label,
                        dash_array=[None, "10 5", "3 5"][index % 3]).add_to(layer)
        photo_points = folium.FeatureGroup(control=False)
        photo_points.add_to(layer)
        point_layers.append(photo_points)
        for point in data["image_points"]:
            elevation = point.get("elevation_meters")
            elevation_label = "unavailable" if elevation is None else f"{elevation:.2f} m"
            folium.CircleMarker(
                [point["latitude"], point["longitude"]], radius=3,
                color=color, weight=1, fill=True, fill_color=color, fill_opacity=0.8,
                pane="route-photo-points",
                tooltip=f"{safe_label} | point {point['location_index']} | {html.escape(point['selection_reason'])} | Elevation: {elevation_label}",
            ).add_to(photo_points)
        for coordinate, text in [(data["route_points"][0], "Start"),
                                 (data["route_points"][-1], "End")]:
            folium.Marker(coordinate, pane="route-photo-points", icon=folium.DivIcon(
                html=f'<div style="white-space:nowrap;font: bold 11px sans-serif;color:{color};background:white;border:1px solid {color};border-radius:4px;padding:2px 4px;width:max-content">{html.escape(data["route_id"])} {text}</div>'
            ), tooltip=safe_label).add_to(layer)
        layer.add_to(route_map)
        layers.append((layer, label, data["route_points"]))
        bounds.extend(data["route_points"])
    if bounds:
        route_map.fit_bounds(bounds)
    folium.LayerControl(collapsed=False).add_to(route_map)

    # Use actual Leaflet layer references to show one route, all routes, or none.
    controls = MacroElement()
    controls._template = Template(r"""
    {% macro script(this, kwargs) %}
    (function () {
        var map = {{ this.map_name }};
        var routes = [{{ this.layer_refs | safe }}];
        var labels = {{ this.labels | safe }};
        var coordinates = {{ this.coordinates | safe }};
        var pointLayers = [{{ this.point_refs | safe }}];
        function updatePoints() {
            var show = map.getZoom() >= {{ this.point_zoom }};
            map.getPane('route-photo-points').style.display = show ? 'block' : 'none';
            routes.forEach(function(route, i) {
                if (show) {
                    if (!route.hasLayer(pointLayers[i])) { route.addLayer(pointLayers[i]); }
                } else {
                    if (route.hasLayer(pointLayers[i])) { route.removeLayer(pointLayers[i]); }
                }
            });
        }
        map.on('zoomend overlayadd', updatePoints);
        map.whenReady(updatePoints);
        var control = L.control({position: 'topleft'});
        control.onAdd = function () {
            var box = L.DomUtil.create('div');
            box.style.cssText = 'background:white;padding:10px;border-radius:5px;box-shadow:0 1px 6px #999;max-width:300px;font:13px sans-serif';
            var title = document.createElement('strong');
            title.textContent = 'Inspect overlapping routes';
            box.appendChild(title);
            var select = document.createElement('select');
            select.style.cssText = 'display:block;width:100%;margin-top:7px';
            select.add(new Option('Show all routes', 'all'));
            select.add(new Option('Hide all routes', 'none'));
            labels.forEach(function(label, i) {select.add(new Option(label, String(i)));});
            box.appendChild(select);
            var hint = document.createElement('div');
            hint.textContent = 'Choose a route to inspect. Zoom in to see photo points.';
            hint.style.cssText = 'margin-top:6px;max-width:270px;color:#555';
            box.appendChild(hint);
            L.DomEvent.disableClickPropagation(box);
            L.DomEvent.disableScrollPropagation(box);
            select.onchange = function () {
                routes.forEach(function(layer, i) {
                    if (select.value === 'all' || select.value === String(i)) {
                        map.addLayer(layer);
                    } else {map.removeLayer(layer);}
                });
                if (select.value !== 'all' && select.value !== 'none') {
                    map.fitBounds(coordinates[Number(select.value)], {padding:[35,35]});
                } else if (select.value === 'all' && coordinates.length) {
                    map.fitBounds(coordinates.flat(), {padding:[25,25]});
                }
            };
            return box;
        };
        control.addTo(map);
    })();
    {% endmacro %}
    """)
    controls.point_refs = ",".join(layer.get_name() for layer in point_layers)
    controls.point_zoom = int(point_zoom)
    controls.map_name = route_map.get_name()
    controls.layer_refs = ",".join(layer.get_name() for layer, _, _ in layers)
    # Escape '<' so CSV labels cannot close the containing script element.
    controls.labels = json.dumps([label for _, label, _ in layers]).replace("<", "\\u003c")
    controls.coordinates = json.dumps([points for _, _, points in layers])
    controls.add_to(route_map)
    route_map.save(str(base / map_filename))
    print(f"{title}: {len(layers)}/{len(expected)} routes plotted. Saved {map_filename}.")
    return route_map
