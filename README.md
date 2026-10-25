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
