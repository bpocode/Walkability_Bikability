import base64
import csv
import json
from html import escape
from pathlib import Path

import folium
import streamlit as st
from streamlit.components.v1 import html

PROJECT = Path(__file__).resolve().parent.parent
MAP_HEIGHT = 700
METERS_PER_MILE = 1609.344
METERS_PER_FOOT = 0.3048


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


def show_map(routes, labels, selected_route):
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

    if selected_route is not None:
        add_photo_points(route_map, routes[selected_route])

    route_map.fit_bounds(bounds)
    html(route_map.get_root().render(), height=MAP_HEIGHT)


def add_photo_points(route_map, route):
    """Add numbered points with a popup for each saved photo."""
    for point in route["image_points"]:
        location = (point["latitude"], point["longitude"])
        label = f"Point {point['location_index'] + 1}"
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

        folium.CircleMarker(
            location,
            radius=6,
            color="#23754a" if photo else "#666666",
            fill=True,
            fill_opacity=0.75,
            tooltip=label,
            popup=folium.Popup(content, max_width=400, lazy=True),
        ).add_to(route_map)


def show_elevation_chart(route):
    """Plot saved elevations against cumulative distance along the route."""
    samples = []
    for point in route["image_points"]:
        distance = point.get("distance_along_route_meters")
        elevation = point.get("elevation_meters")
        if distance is not None and elevation is not None:
            samples.append({
                "Distance (mi)": distance / METERS_PER_MILE,
                "Elevation (ft)": elevation / METERS_PER_FOOT,
            })

    st.subheader("Elevation profile")
    if len(samples) < 2:
        st.caption("There are too few saved elevation points to plot this route.")
        return

    st.line_chart(samples, x="Distance (mi)", y="Elevation (ft)", height=250)


def select_route(route_id=None):
    st.session_state.selected_route = route_id


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
    st.write("Placeholder: Add the update date and a short summary of what changed.")
with current_status:
    st.subheader("Current status")
    st.write("Placeholder: Summarize what the team is working on now.")
with next_milestone:
    st.subheader("Next milestone")
    st.write("Placeholder: Describe the next deliverable and its target date.")

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
    "and **−** to zoom. Drag to pan. Click a green point to open its photo. "
    "Gray points have no saved photo."
)
map_column, details_column = st.columns([2, 1])
with map_column:
    show_map(routes, labels, selected_route)
with details_column:
    with st.container(height=MAP_HEIGHT, border=False):
        st.subheader(f"{mode} routes")
        list_height = 240 if selected_route is not None else 520
        show_route_table(names, distances, selected_route, list_height)
        if selected_route is not None:
            show_elevation_chart(routes[selected_route])
