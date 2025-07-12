import streamlit as st
import requests
import time
import logging
from itertools import product
import numpy as np

logger = logging.getLogger(__name__)

class PharmacyService:
    """Service pour interagir avec l'API Google Places (New) pour collecter les pharmacies."""

    def __init__(self):
        """Initialiser le service avec la clé API Google."""
        self.api_key = st.secrets.get("GOOGLE_API_KEY")
        if not self.api_key:
            st.error("Erreur : la clé API Google n'est pas définie dans les secrets.")
            logger.error("Clé API Google non définie dans les secrets")
            raise ValueError("Clé API Google manquante")

    def get_pharmacies_in_subarea(self, center_lat, center_lon, radius):
        """Collecter les pharmacies dans une sous-zone via Google Places API (New)."""
        pharmacies = []
        request_count = 0
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
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "places.displayName,places.location,places.formattedAddress"
        }

        try:
            logger.info(f"Envoi de la requête API pour sous-zone ({center_lat:.4f}, {center_lon:.4f})")
            response = requests.post(url, json=payload, headers=headers)
            request_count += 1
            response.raise_for_status()
            data = response.json()

            for place in data.get("places", []):
                lat = place["location"]["latitude"]
                lon = place["location"]["longitude"]
                name = place.get("displayName", {}).get("text", "Pharmacie sans nom")
                address = place.get("formattedAddress", "Adresse inconnue")
                pharmacies.append({
                    "name": name,
                    "address": address,
                    "latitude": lat,
                    "longitude": lon
                })
                logger.info(f"Pharmacie ajoutée : {name}, ({lat:.4f}, {lon:.4f})")

            while "nextPageToken" in data:
                time.sleep(2)
                payload["pageToken"] = data["nextPageToken"]
                logger.info(f"Envoi de la requête pour la page suivante (token: {data['nextPageToken']})")
                response = requests.post(url, json=payload, headers=headers)
                request_count += 1
                response.raise_for_status()
                data = response.json()
                for place in data.get("places", []):
                    lat = place["location"]["latitude"]
                    lon = place["location"]["longitude"]
                    name = place.get("displayName", {}).get("text", "Pharmacie sans nom")
                    address = place.get("formattedAddress", "Adresse inconnue")
                    pharmacies.append({
                        "name": name,
                        "address": address,
                        "latitude": lat,
                        "longitude": lon
                    })
                    logger.info(f"Pharmacie ajoutée : {name}, ({lat:.4f}, {lon:.4f})")
            st.write(
                f"Requête pour sous-zone ({center_lat:.4f}, {center_lon:.4f}) : {request_count} requêtes effectuées")
            logger.info(
                f"Sous-zone ({center_lat:.4f}, {center_lon:.4f}) : {len(pharmacies)} pharmacies trouvées, {request_count} requêtes")

        except requests.exceptions.RequestException as e:
            st.error(f"Erreur pour sous-zone ({center_lat:.4f}, {center_lon:.4f}) : {e}")
            logger.error(f"Erreur pour sous-zone ({center_lat:.4f}, {center_lon:.4f}) : {e}")
            if 'response' in locals() and response.text:
                st.error(f"Détails de l'erreur : {response.text}")
                logger.error(f"Détails de l'erreur : {response.text}")
            return [], request_count

        return pharmacies, request_count

    def get_pharmacies_in_area(self, lat_min, lat_max, lon_min, lon_max, subarea_step, subarea_radius):
        """Collecter les pharmacies dans une zone donnée."""
        try:
            logger.info(f"Début de la recherche de pharmacies : bounds=({lat_min:.4f}, {lat_max:.4f}, {lon_min:.4f}, {lon_max:.4f}), step={subarea_step}, radius={subarea_radius}")
            if not (lat_min < lat_max and lon_min < lon_max):
                logger.error("Les limites de la zone sont invalides")
                st.error("Les limites de la zone sont invalides. Vérifiez les coordonnées.")
                return [], 0

            pharmacies = []
            total_requests = 0
            lat_points = np.arange(lat_min, lat_max, subarea_step)
            lon_points = np.arange(lon_min, lon_max, subarea_step)
            subarea_centers = list(product(lat_points, lon_points))

            st.write(f"Nombre de sous-zones à traiter : {len(subarea_centers)}")
            logger.info(f"Collecte des pharmacies pour {len(subarea_centers)} sous-zones")

            for center_lat, center_lon in subarea_centers:
                subarea_pharmacies, request_count = self.get_pharmacies_in_subarea(center_lat, center_lon, subarea_radius)
                pharmacies.extend(subarea_pharmacies)
                total_requests += request_count

            unique_pharmacies = []
            seen = set()
            for p in pharmacies:
                key = (p["latitude"], p["longitude"], p["name"])
                if key not in seen:
                    seen.add(key)
                    unique_pharmacies.append(p)

            st.write(f"Nombre total de requêtes effectuées pour la collecte : {total_requests}")
            logger.info(f"Collecte terminée : {len(unique_pharmacies)} pharmacies uniques, {total_requests} requêtes")
            return unique_pharmacies, total_requests

        except Exception as e:
            st.error(f"Erreur inattendue lors de la recherche des pharmacies : {e}")
            logger.error(f"Erreur inattendue lors de la recherche des pharmacies : {e}")
            return [], 0