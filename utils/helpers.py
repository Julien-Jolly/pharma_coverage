import hashlib
import numpy as np

def estimate_bounds(center_lat, center_lon, zoom):
    """Estimer une bounding box à partir du centre et du zoom."""
    delta = 0.05 / (2 ** (zoom - 12))
    lat_min = center_lat - delta
    lat_max = center_lat + delta
    lon_min = center_lon - delta
    lon_max = center_lon + delta
    return lat_min, lat_max, lon_min, lon_max

def generate_pharmacies_key(pharmacies):
    """Générer une clé unique pour une liste de pharmacies."""
    return hashlib.md5(str([(p['latitude'], p['longitude'], p['name']) for p in pharmacies]).encode()).hexdigest()

def get_bounds_key(bounds):
    """Génère une clé unique pour des coordonnées de zone (bounds)."""
    return hashlib.md5(str(bounds).encode()).hexdigest()
