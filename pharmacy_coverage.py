import time
import folium
import numpy as np
import pandas as pd
from geopy.distance import geodesic
from itertools import product
import xml.etree.ElementTree as ET
import os
from dotenv import load_dotenv
import requests

# Charger les variables d'environnement depuis le fichier .env
load_dotenv()

# Récupérer la clé API Google depuis le fichier .env
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise ValueError("Erreur : la clé API Google n'est pas définie dans le fichier .env")


# Fonction pour charger les coordonnées depuis un fichier OSM
def load_osm_bounds(file_path):
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        bounds = root.find("bounds")
        if bounds is None:
            raise ValueError("Aucun élément <bounds> trouvé dans le fichier OSM.")
        lat_min = float(bounds.get("minlat"))
        lat_max = float(bounds.get("maxlat"))
        lon_min = float(bounds.get("minlon"))
        lon_max = float(bounds.get("maxlon"))
        return lat_min, lat_max, lon_min, lon_max
    except Exception as e:
        print(f"Erreur lors du chargement du fichier OSM : {e}")
        return None


# Fonction pour obtenir les coordonnées manuellement
def get_manual_bounds():
    print("Entrez les coordonnées de la bounding box manuellement :")
    try:
        lat_min = float(input("Latitude minimale (sud) : "))
        lat_max = float(input("Latitude maximale (nord) : "))
        lon_min = float(input("Longitude minimale (ouest) : "))
        lon_max = float(input("Longitude maximale (est) : "))
        return lat_min, lat_max, lon_min, lon_max
    except ValueError:
        print("Erreur : veuillez entrer des valeurs numériques valides.")
        return None


# Fonction pour collecter les pharmacies dans une sous-zone avec Places API (New)
def get_pharmacies_in_subarea(center_lat, center_lon, radius=1000):
    pharmacies = []
    request_count = 0  # Compteur de requêtes
    url = "https://places.googleapis.com/v1/places:searchNearby"

    payload = {
        "locationRestriction": {
            "circle": {
                "center": {
                    "latitude": center_lat,
                    "longitude": center_lon
                },
                "radius": radius
            }
        },
        "includedTypes": ["pharmacy"],
        "maxResultCount": 20
    }

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": "places.displayName,places.location"
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        request_count += 1
        response.raise_for_status()
        data = response.json()

        for place in data.get("places", []):
            lat = place["location"]["latitude"]
            lon = place["location"]["longitude"]
            pharmacies.append({
                "name": place.get("displayName", {}).get("text", "Pharmacie sans nom"),
                "latitude": lat,
                "longitude": lon
            })

        while "nextPageToken" in data:
            time.sleep(2)
            payload["pageToken"] = data["nextPageToken"]
            response = requests.post(url, json=payload, headers=headers)
            request_count += 1
            response.raise_for_status()
            data = response.json()
            for place in data.get("places", []):
                lat = place["location"]["latitude"]
                lon = place["location"]["longitude"]
                pharmacies.append({
                    "name": place.get("displayName", {}).get("text", "Pharmacie sans nom"),
                    "latitude": lat,
                    "longitude": lon
                })
        print(f"Requête pour sous-zone ({center_lat}, {center_lon}) : {request_count} requêtes effectuées")

    except requests.exceptions.RequestException as e:
        print(f"Erreur pour sous-zone ({center_lat}, {center_lon}) : {e}")
        if response.text:
            print(f"Détails de l'erreur : {response.text}")

    return pharmacies, request_count


# Fonction pour collecter les pharmacies dans la bounding box en divisant en sous-zones
def get_pharmacies_in_area(lat_min, lat_max, lon_min, lon_max, subarea_step=0.01, subarea_radius=1000):
    pharmacies = []
    total_requests = 0

    # Créer une grille de sous-zones
    lat_points = np.arange(lat_min, lat_max, subarea_step)
    lon_points = np.arange(lon_min, lon_max, subarea_step)
    subarea_centers = list(product(lat_points, lon_points))

    print(f"Nombre de sous-zones à traiter : {len(subarea_centers)}")

    # Effectuer une requête pour chaque sous-zone
    for center_lat, center_lon in subarea_centers:
        subarea_pharmacies, request_count = get_pharmacies_in_subarea(center_lat, center_lon, subarea_radius)
        pharmacies.extend(subarea_pharmacies)
        total_requests += request_count

    # Supprimer les doublons (basé sur latitude, longitude et nom)
    unique_pharmacies = []
    seen = set()
    for p in pharmacies:
        key = (p["latitude"], p["longitude"], p["name"])
        if key not in seen:
            seen.add(key)
            unique_pharmacies.append(p)

    print(f"Nombre total de requêtes effectuées pour la collecte des pharmacies : {total_requests}")
    return unique_pharmacies, total_requests


# Fonction pour calculer la distance à vol d'oiseau
def is_within_radius(point, pharmacy, radius_m=300):
    point_coords = (point[0], point[1])
    pharmacy_coords = (pharmacy['latitude'], pharmacy['longitude'])
    distance = geodesic(point_coords, pharmacy_coords).meters
    return distance <= radius_m


# Créer une grille de points pour l'analyse des zones sans pharmacie
def create_grid(lat_min, lat_max, lon_min, lon_max, step=0.001):
    lat_points = np.arange(lat_min, lat_max, step)
    lon_points = np.arange(lon_min, lon_max, step)
    grid = list(product(lat_points, lon_points))
    return grid


# Trouver les zones sans pharmacie dans un rayon de 300m
def find_no_pharmacy_zones(pharmacies, grid, radius_m=300):
    no_pharmacy_zones = []
    for point in grid:
        within_radius = any(is_within_radius(point, pharmacy, radius_m) for pharmacy in pharmacies)
        if not within_radius:
            no_pharmacy_zones.append(point)
    return no_pharmacy_zones


# Créer une carte avec Folium
def create_map(pharmacies, no_pharmacy_zones, center_lat, center_lon):
    m = folium.Map(location=[center_lat, center_lon], zoom_start=12)

    # Ajouter les pharmacies sur la carte
    for pharmacy in pharmacies:
        folium.Marker(
            location=[pharmacy['latitude'], pharmacy['longitude']],
            popup=pharmacy['name'],
            icon=folium.Icon(color='green', icon='plus')
        ).add_to(m)

    # Ajouter les zones sans pharmacie
    for point in no_pharmacy_zones:
        folium.CircleMarker(
            location=[point[0], point[1]],
            radius=3,
            color='red',
            fill=True,
            fill_color='red',
            fill_opacity=0.6
        ).add_to(m)

    return m


# Exécuter le script
def main():
    # Demander à l'utilisateur de fournir un fichier OSM
    osm_file = input("Entrez le chemin du fichier OSM (ou laissez vide pour saisir manuellement) : ")

    # Charger les coordonnées
    if osm_file and os.path.exists(osm_file):
        bounds = load_osm_bounds(osm_file)
        if bounds:
            lat_min, lat_max, lon_min, lon_max = bounds
            print(f"Coordonnées chargées depuis le fichier OSM :")
            print(f"lat_min={lat_min}, lat_max={lat_max}, lon_min={lon_min}, lon_max={lon_max}")
        else:
            print("Impossible de charger les coordonnées depuis le fichier OSM.")
            bounds = get_manual_bounds()
    else:
        print("Aucun fichier OSM fourni ou fichier invalide.")
        bounds = get_manual_bounds()

    if not bounds:
        print("Erreur : impossible d'obtenir les coordonnées. Fin du programme.")
        return

    lat_min, lat_max, lon_min, lon_max = bounds

    # Vérifier la validité des coordonnées
    if not (lat_min < lat_max and lon_min < lon_max):
        print("Erreur : les coordonnées de la bounding box sont invalides.")
        return

    print("Collecte des pharmacies via Google Places API (New) avec grille de sous-zones...")
    pharmacies, total_requests = get_pharmacies_in_area(lat_min, lat_max, lon_min, lon_max, subarea_step=0.01,
                                                        subarea_radius=1000)
    if not pharmacies:
        print("Aucune pharmacie trouvée dans la zone. Vérifiez votre clé API Google ou essayez une zone plus large.")
        print(
            "Vous pouvez vérifier manuellement sur https://www.google.com/maps en recherchant 'pharmacy' dans la zone.")
        return

    print(f"{len(pharmacies)} pharmacies trouvées (après déduplication).")
    df_pharmacies = pd.DataFrame(pharmacies)
    print(df_pharmacies[['name', 'latitude', 'longitude']])

    print("Création de la grille pour l'analyse des zones sans pharmacie...")
    grid = create_grid(lat_min, lat_max, lon_min, lon_max, step=0.001)

    print("Identification des zones sans pharmacie...")
    no_pharmacy_zones = find_no_pharmacy_zones(pharmacies, grid, radius_m=300)

    print(f"{len(no_pharmacy_zones)} points sans pharmacie dans un rayon de 300m.")
    print(f"Nombre total de requêtes effectuées pour l'ensemble du script : {total_requests}")

    # Créer et sauvegarder la carte
    center_lat = (lat_min + lat_max) / 2
    center_lon = (lon_min + lon_max) / 2
    map_obj = create_map(pharmacies, no_pharmacy_zones, center_lat, center_lon)
    map_obj.save("pharmacy_coverage_map.html")
    print("Carte sauvegardée sous 'pharmacy_coverage_map.html'.")


if __name__ == "__main__":
    main()