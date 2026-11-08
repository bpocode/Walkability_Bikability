# Walking and Biking Image-Location Points

This repository displays saved walking and biking routes and their proposed
image-location points on interactive Folium maps.

The notebook reads the included JSON files directly. It does not contact the
Google Routes API, the Google Elevation API, or any other Google API, and it
does not require an API key.

## Files

```text
.
├── Walking_and_Biking_Points.ipynb
├── requirements.txt
└── saved_route_points/
    ├── walking_routes.json
    └── biking_routes.json
```

## Run locally

1. Clone or download this repository.
2. Install the dependency:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Open `Walking_and_Biking_Points.ipynb` in Jupyter Notebook or JupyterLab.
4. Run all cells from top to bottom.

The walking and biking maps are created independently from the files in
`saved_route_points/`.

## Saved data

Each JSON file contains route geometry, route metadata, and the previously
generated image-location points. Some points also include saved elevation
values. The notebook only visualizes these stored values; it does not
regenerate or update them.

## Generate routes and images with master.py

`master.py` is a standalone file with three main functions:

- `get_route(origin, destination, travel_mode="WALK", api_key=None)` returns a list of `(latitude, longitude)` coordinates. Use `"BICYCLE"` for biking.
- `get_image_points(route_points)` selects points every **100 feet for walking** or **150 feet for biking** along the route, plus endpoints and turns of at least 30 degrees. Selections within one meter are merged, matching the original methodology. It returns dictionaries containing coordinates, headings, distance, and selection reason, so some selected points are closer than the regular spacing.
- `get_images(points, pitch=-5, output_folder="route_images", api_key=None)` downloads the images and returns their file paths. It accepts the dictionaries above or ordinary coordinate pairs. Missing imagery is printed and skipped. Other request errors stop the function; images already saved remain on disk.

Install dependencies with `python -m pip install -r requirements.txt`.
Copy `.env.example` to `.env` next to `master.py`, then paste your own key after `GOOGLE_MAPS_API_KEY=`. This file is automatically loaded and excluded from Git. Use a Google Maps key with Routes API and Street View Static API enabled, or pass `api_key` to the first and third functions. Live calls can incur Google API charges. Importing the file makes no requests.

From this folder, use:

```python
from master import get_route, get_image_points, get_images

origin = (35.245798, -120.637092)
destination = (35.238287, -120.637968)

route = get_route(origin, destination, travel_mode="WALK")
points = get_image_points(route)
images = get_images(points, pitch=-5, output_folder="Walking Points/R001")

print(f"Saved {len(images)} images")
```

For biking, pass `travel_mode="BICYCLE"` to `get_route`, `get_image_points`, and `get_images`; change the mode to `"BICYCLE"` and the output folder to, for example, `"Biking Points/R001"`. Choose the folder for the route you are processing.

Pitch is the vertical camera angle: negative looks down, zero is level, and positive looks up (range -90 to 90). Images use a 40-degree offset for walking and a 15-degree offset for biking from the route heading, 600 × 400 pixels, and a 100-degree field of view. Filenames use actual panorama coordinates, camera heading, and capture month: `sv_lat35.246530_lon-120.642063_h114.574_2025-09.jpg`. Coordinates have six decimal places and headings have three. Pitch is stored in JSON; changing pitch replaces the matching filename. This simple downloader does not perform the old downloader's panorama deduplication or write its metadata CSV.

API references: [Google Routes](https://developers.google.com/maps/documentation/routes/compute_route_directions), [Street View parameters](https://developers.google.com/maps/documentation/streetview/request-streetview).

## Collect all Test Routes

Open `Route_Data_Collection.ipynb` and run its cells from top to bottom. Its **Data Collection** section reads both CSVs in `Test Routes`, requests walking/biking routes, selects 100-foot walking or 150-foot biking points plus turn points, fetches their elevations, and downloads photos using the configured pitch.

Each `Walking Photos/<route_id>/` or `Biking Photos/<route_id>/` folder receives photos, `route_points.json` (full route geometry plus selected photo points and elevations), and `point_images.csv` (coordinates, elevation, camera settings, filename, and availability). Elevations describe the requested points, which can differ from Google's nearest available Street View panorama locations.

The final cell displays separate walking and biking maps and saves `walking_routes_map.html` and `biking_routes_map.html`. It reads saved collection JSON without making Google API calls. Route layers show the complete street geometry; markers show the selected photo points. The notebook reports how many of the 27 routes per mode were available to plot.

Enable Google Routes, Elevation, and Street View Static APIs for your `.env` key. Collection makes live API requests and may incur charges. Saved matching geometry/elevations and verified matching photos are reused; missing imagery is retried. Failed routes are reported and other routes continue. No live collection was run when this notebook was created.

## Image storage and availability

`get_images` writes `point_images.json` in its output folder, including when
called directly. `save_route_images` also stores those fields in each
`route_points.json` image point and exports them to `point_images.csv`.
Each point keeps requested latitude/longitude separately from `image_latitude`,
`image_longitude`, `camera_heading`, `capture_month`, `panorama_id`, `pitch`,
and `image_offset_meters`. `image_filename` is the exact filename relative to
the route folder, preserving trailing zeros. The manifest supports reuse without
parsing or reconstructing filenames.

Missing coverage or an image HTTP 404 records `status: "unavailable"` and
`image_filename: null`; no path is returned for that point. Wider nearby-image
fallback is disabled. The initial Street View search remains within 50 meters,
so available panorama coordinates can differ from requested coordinates.
Missing capture-month metadata records `capture_date_unavailable` and returns
no image. Request failures record `error` and stop collection rather than being
classified as missing coverage. Successful points have `status: "saved"`.

Existing legacy photos are preserved. Their filenames do not contain verified
capture dates, so they are not automatically renamed or reused by this workflow.
Run collection to populate the new metadata and filenames (Google API calls).


## Collaborating

Use this repository: https://github.com/bpocode/Walkability_Bikability.
The owner should invite teammates through the repository's Settings → Collaborators.
Teammates should accept the invitation, clone this repository, and work on a
separate branch for each task:

```bash
git clone https://github.com/bpocode/Walkability_Bikability.git
cd Walkability_Bikability
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install jupyterlab

git switch main
git pull --ff-only
git switch -c improve-route-maps
```

On Windows, activate the environment with `.venv\Scripts\activate` instead.
Run `jupyter lab` to open the notebooks. Saved route visualization needs no API
key. For live collection, copy `.env.example` to `.env` and supply your own key.
Local credentials, collected photos, and generated map HTML are excluded from
Git; collaborators will not receive these files when cloning. Arrange a separate
shared location for collected photos if the team needs the same dataset.

Before committing, clear notebook outputs using Jupyter's **Clear All Outputs**
command and save the notebook. Embedded maps and photos can make notebooks very
large. Coordinate notebook editing so two people do not edit the same notebook
at once. Keep the route CSVs and saved route JSON files in Git.

Review `git status` and your diff, commit only the files for your task, then push
your branch and open a pull request into `main`. Have a teammate review it before
merging. The owner should configure protection for `main` to require pull
requests and a review, where the repository's GitHub plan supports this.

Run the offline checks before submitting code changes:

```bash
python -m unittest discover -s tests -v
```
