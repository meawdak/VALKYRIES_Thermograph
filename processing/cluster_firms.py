import glob
import pandas as pd
import numpy as np
from sklearn.cluster import DBSCAN


# -----------------------------
# 1. Load all FIRMS CSV files
# -----------------------------

files = glob.glob("data/firms/chunks/*.csv")

df = pd.concat(
    (pd.read_csv(file) for file in files),
    ignore_index=True
)

print(f"Loaded {len(df)} FIRMS detections.")


# -----------------------------
# 2. Prepare coordinates
# -----------------------------

# Make sure latitude and longitude are numeric
df["latitude"] = pd.to_numeric(df["latitude"])
df["longitude"] = pd.to_numeric(df["longitude"])

coordinates = df[["latitude", "longitude"]].to_numpy()

# Convert degrees to radians because DBSCAN
# will use the Haversine distance.
coordinates_rad = np.radians(coordinates)


# -----------------------------
# 3. Cluster nearby detections
# -----------------------------

# Earth's radius in kilometres
EARTH_RADIUS_KM = 6371.0088

# Prototype starting parameters
DISTANCE_KM = 1.0
MIN_DETECTIONS = 5

# DBSCAN's eps must be expressed in radians
epsilon = DISTANCE_KM / EARTH_RADIUS_KM

model = DBSCAN(
    eps=epsilon,
    min_samples=MIN_DETECTIONS,
    metric="haversine",
    algorithm="ball_tree"
)

df["cluster_id"] = model.fit_predict(coordinates_rad)


# -----------------------------
# 4. Separate clustered points
#    from noise
# -----------------------------

clustered = df[df["cluster_id"] != -1].copy()

noise_count = len(df) - len(clustered)
site_count = clustered["cluster_id"].nunique()

print(f"Detections assigned to clusters: {len(clustered)}")
print(f"Noise detections: {noise_count}")
print(f"Candidate thermal sites: {site_count}")


# -----------------------------
# 5. Create thermal-site summary
# -----------------------------

sites = (
    clustered
    .groupby("cluster_id")
    .agg(
        latitude=("latitude", "mean"),
        longitude=("longitude", "mean"),
        detection_count=("cluster_id", "size"),
        active_dates=("acq_date", "nunique"),
        first_seen=("acq_date", "min"),
        last_seen=("acq_date", "max"),
        mean_frp=("frp", "mean"),
        max_frp=("frp", "max")
    )
    .reset_index()
)


# -----------------------------
# 6. Create readable site IDs
# -----------------------------

sites["site_id"] = (
    "SITE_"
    + sites["cluster_id"].astype(int).astype(str).str.zfill(5)
)


# -----------------------------
# 7. Keep the useful columns
# -----------------------------

sites = sites[
    [
        "site_id",
        "latitude",
        "longitude",
        "detection_count",
        "active_dates",
        "first_seen",
        "last_seen",
        "mean_frp",
        "max_frp"
    ]
]


# -----------------------------
# 8. Save processed result
# -----------------------------

sites.to_csv(
    "output/thermal_sites.csv",
    index=False
)

print("Saved: output/thermal_sites.csv")
