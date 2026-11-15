import base64
import csv
import json
from html import escape
from pathlib import Path

import altair as alt
import folium
import streamlit as st
from folium.elements import EventHandler
from folium.utilities import JsCode
from streamlit.components.v1 import html

PROJECT = Path(__file__).resolve().parent.parent
MAP_HEIGHT = 700
METERS_PER_MILE = 1609.344
METERS_PER_FOOT = 0.3048

route_map_component = st.components.v2.component(
    "route_point_map",
    html=f'<iframe title="Route map" style="display:block;width:100%;height:{MAP_HEIGHT}px;border:0"></iframe>',
    js=Path(__file__).with_name("route_map.js").read_text(encoding="utf-8"),
)


def load_routes(mode):
    """Read the collection's saved routes and match points to local photos."""
    routes = {}
    for route_file in sorted((PROJECT / f"{mode} Photos").glob("*/route_points.json")):
        route = json.loads(route_file.read_text(encoding="utf-8"))
        manifest = route_file.with_name("point_images.csv")
        photos = {}
        if manifest.is_file():
            with manifest.open(newline="", encoding="utf-8-sig") as file:
                for row in csv.DictReader(file):
                    filename = row.get("image_filename")
                    if filename:
                        path = manifest.parent / Path(filename).name
                        if path.is_file():
                            photos[row["location_index"]] = path

        for point in route["image_points"]:
            point["photo"] = photos.get(str(point["location_index"]))
        routes[route_file.parent.name] = route
    return routes


def load_route_names(mode):
    """Use the neighborhood and destination from the route inventory."""
    inventory = PROJECT / "Test Routes" / f"origins_and_destinations_{mode.lower()}.csv"
    if not inventory.is_file():
        return {}
    with inventory.open(newline="", encoding="utf-8-sig") as file:
        return {
            row["route_id"]: f'{row["neighborhood"]} to {row["destination_name"]}'
            for row in csv.DictReader(file)
        }


def route_distance_miles(route):
    """Use the saved cumulative distance at the end of the route."""
    distance = max(
        (point["distance_along_route_meters"] for point in route["image_points"]
         if "distance_along_route_meters" in point),
        default=None,
    )
    return distance / METERS_PER_MILE if distance is not None else None


def route_label(name, miles):
    if miles is None:
        return name
    return f"{name} · {miles:.2f} mi"


def show_map(routes, labels, selected_route, mode):
    """Draw the coverage for this mode or show photos on a single route."""
    route_map = folium.Map()
    bounds = []
    for route_id, route in routes.items():
        if selected_route is not None and route_id != selected_route:
            continue
        geometry = route["route_points"]
        bounds.extend(geometry)
        folium.PolyLine(
            geometry, color="#285a86", weight=4, tooltip=escape(labels[route_id])
        ).add_to(route_map)

    route_map.fit_bounds(bounds)
    if selected_route is None:
        html(route_map.get_root().render(), height=MAP_HEIGHT)
        return None

    add_photo_points(route_map, routes[selected_route])
    result = route_map_component(
        key=f"map_{mode}_{selected_route}",
        data={"route": f"{mode}/{selected_route}", "mapHtml": route_map.get_root().render()},
        height=MAP_HEIGHT,
        on_point_change=lambda: None,
    )
    if result.point is not None:
        st.session_state.selected_point = result.point
    return st.session_state.selected_point


def add_photo_points(route_map, route):
    """Add numbered points with a popup for each saved photo."""
    previous_distance = None
    for point in route["image_points"]:
        location = (point["latitude"], point["longitude"])
        label = f"Point {point['location_index'] + 1}"
        endpoint = point.get("selection_reason")
        if endpoint in ("origin", "destination"):
            label += " · Start" if endpoint == "origin" else " · Finish"
        photo = point["photo"]
        if photo:
            encoded = base64.b64encode(photo.read_bytes()).decode("ascii")
            content = (
                f'<strong>{label}</strong><br>'
                f'<img src="data:image/jpeg;base64,{encoded}" '
                f'alt="Street-level photo at {label.lower()}" '
                'style="width:360px;max-width:65vw;height:auto">'
            )
        else:
            content = f"{label} · No saved photo"

        elevation = point.get("elevation_meters")
        if elevation is not None:
            content += f"<br>Elevation: {elevation / METERS_PER_FOOT:,.0f} ft"

        distance = point.get("distance_along_route_meters")
        if distance is not None and previous_distance is not None:
            content += f"<br>From previous point: {(distance - previous_distance) / METERS_PER_FOOT:,.0f} ft"
        previous_distance = distance

        popup = folium.Popup(content, max_width=400, lazy=True)
        if endpoint in ("origin", "destination"):
            start = endpoint == "origin"
            marker = folium.Marker(
                location, tooltip=label, popup=popup,
                icon=folium.Icon(
                    color="green" if start else "red",
                    icon="play" if start else "flag-checkered",
                    prefix="fa",
                ),
            )
        else:
            marker = folium.CircleMarker(
                location, radius=6, color="#23754a" if photo else "#666666",
                fill=True, fill_opacity=0.75, tooltip=label, popup=popup,
            )
        marker.add_to(route_map)
        marker.add_child(EventHandler("click", JsCode(
            "function () { window.parent.postMessage("
            f"{{type: 'route-point', index: {int(point['location_index'])}}}, window.origin); }}"
        )))


def show_elevation_chart(route, selected_point):
    """Plot saved elevations against cumulative distance along the route."""
    samples = []
    for point in route["image_points"]:
        distance = point.get("distance_along_route_meters")
        elevation = point.get("elevation_meters")
        if distance is not None and elevation is not None:
            samples.append({
                "Point": point["location_index"],
                "Distance (mi)": distance / METERS_PER_MILE,
                "Elevation (ft)": elevation / METERS_PER_FOOT,
            })

    st.subheader("Elevation profile")
    if len(samples) < 2:
        st.caption("There are too few saved elevation points to plot this route.")
        return

    chart = alt.Chart(alt.Data(values=samples)).encode(
        x=alt.X("Distance (mi):Q"),
        y=alt.Y("Elevation (ft):Q", scale=alt.Scale(zero=False)),
        tooltip=["Distance (mi):Q", "Elevation (ft):Q"],
    )
    profile = chart.mark_line()
    if any(sample["Point"] == selected_point for sample in samples):
        highlight = chart.transform_filter(alt.datum.Point == selected_point).mark_circle(
            size=110, color="#c2410c", opacity=1
        )
        profile = profile + highlight
    st.altair_chart(profile.properties(height=250))


def select_route(route_id=None):
    st.session_state.selected_route = route_id
    st.session_state.selected_point = None


def show_route_table(names, distances, selected_route, height):
    """Show route buttons and distances in a vertically scrolling list."""
    st.button(
        "Show all routes",
        type="primary" if selected_route is None else "secondary",
        on_click=select_route,
    )
    st.caption(f"Scroll inside the box to browse all {len(names)} routes.")
    st.html("""
        <style>
        .st-key-route_list { scrollbar-color: #777 transparent; scrollbar-width: auto; }
        .st-key-route_list::-webkit-scrollbar { width: 10px; }
        .st-key-route_list::-webkit-scrollbar-thumb {
            background: #777;
            border-radius: 5px;
        }
        </style>
    """)
    with st.container(height=height, border=True, key="route_list"):
        route_column, miles_column = st.columns([3, 1])
        route_column.markdown("**Route**")
        miles_column.markdown("**Miles**")

        for route_id, name in names.items():
            miles = distances[route_id]
            route_column, miles_column = st.columns([3, 1], vertical_alignment="center")
            route_column.button(
                name,
                key=f"route_{route_id}",
                type="primary" if route_id == selected_route else "secondary",
                use_container_width=True,
                on_click=select_route,
                args=(route_id,),
            )
            miles_column.write(f"{miles:.2f}" if miles is not None else "—")


st.set_page_config(page_title="Walkability & Bikability", layout="wide")
st.title("Walkability & Bikability")

last_update, current_status, next_milestone = st.columns(3)
with last_update:
    st.subheader("Last update")
    st.write("Mapped 27 walking routes and 27 biking routes across San Luis Obispo. The dashboard now shows route distances, street-level photos where available, and elevation profiles.")
with current_status:
    st.subheader("Current status")
    st.write("Exploring vision-language models (VLMs) to identify features in street-level photos.")
with next_milestone:
    st.subheader("Next milestone")
    st.write("Compare candidate VLMs on a sample of route photos and select one for the project.")


if "selected_route" not in st.session_state:
    select_route()

mode = st.radio("Travel mode", ["Walking", "Biking"], horizontal=True, on_change=select_route)
routes = load_routes(mode)
if not routes:
    st.info(f"No saved {mode.lower()} routes were found.")
    st.stop()

st.metric("Routes mapped", len(routes))

route_names = load_route_names(mode)
names = {route_id: route_names.get(route_id, route_id) for route_id in routes}
distances = {route_id: route_distance_miles(route) for route_id, route in routes.items()}
labels = {
    route_id: route_label(names[route_id], distances[route_id])
    for route_id in routes
}
selected_route = st.session_state.selected_route
st.subheader("Route map")
st.caption(
    "Choose a route from the list beside the map to see its photo points, or select "
    "**Show all routes** for the overview. Scroll over the map or use **+** "
    "and **−** to zoom. Drag to pan. Click a point to see its photo and highlight "
    "its elevation. The green play icon marks the start and the red flag marks the finish. "
    "Gray points have no saved photo."
)
map_column, details_column = st.columns([2, 1])
with map_column:
    selected_point = show_map(routes, labels, selected_route, mode)
with details_column:
    with st.container(height=MAP_HEIGHT, border=False):
        st.subheader(f"{mode} routes")
        list_height = 205 if selected_route is not None else 520
        show_route_table(names, distances, selected_route, list_height)
        if selected_route is not None:
            route = routes[selected_route]
            settings = route.get("settings", {})
            spacing = settings.get("spacing_feet")
            offset = settings.get("heading_offset_degrees")
            if spacing is not None and offset is not None:
                st.caption(f"Saved sampling interval: {spacing} ft · Camera offset: {offset:+g}° from route heading")
            show_elevation_chart(route, selected_point)
