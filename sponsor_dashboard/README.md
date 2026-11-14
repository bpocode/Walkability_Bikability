# Walkability & Bikability sponsor dashboard draft

From the `Walkability_Bikability` project folder, run:

```sh
uv run streamlit run sponsor_dashboard/app.py
```

On the first run, `uv` installs the project's dependencies automatically.

Open the local URL printed by Streamlit. Switch between walking and biking to
see the route count and full coverage for that mode. Choose a named route
to see its photo points, then click a green point to open the photo.

The app reads the existing `Walking Photos` and `Biking Photos` folders next to
`sponsor_dashboard` and uses the `Test Routes` CSVs for route names. It does not run the collection pipeline or need a Google
API key. The map needs internet access for its basemap and map libraries.

This draft is for local review. Verify the sharing terms for the saved Street
View photos and route geometry before hosting the dashboard for sponsors.

## Deploy to Streamlit Community Cloud

Commit the `sponsor_dashboard` folder to the deployment branch of the GitHub
repository. The app uses the requirements file beside `app.py`, and reads the
route and photo files already tracked in the repository. No API secrets are
needed. Keep the local-only `.streamlit/config.toml` off the deployment branch.

In [Streamlit Community Cloud](https://share.streamlit.io/), choose **Create
app**, then select the GitHub repository, deployment branch, and
`sponsor_dashboard/app.py` as the main file path. Select Python 3.12 in
**Advanced settings**, which matches the tested local environment.

This repository is public, so Community Cloud defaults to a public app. For
sponsor-only access, deploy from a private repository so access is restricted
from the start. Use the app's **Share** controls to invite viewers by email.
