import streamlit as st
import requests
import time
import logging
import json
import numpy as np
from itertools import product
from typing import Tuple, List, Dict
from datetime import datetime, timedelta
from functools import lru_cache

logger = logging.getLogger(__name__)


class PharmacyService:
    def __init__(self):
        """Initialiser le service de recherche de pharmacies avec la clé API Google."""
        self.api_key = st.secrets.get("GOOGLE_API_KEY")
        if not self.api_key:
            logger.error("Clé API Google non définie dans les secrets")
            st.error("Erreur : la clé API Google n'est pas définie.")
            raise ValueError("Clé API Google manquante")

        # Initialiser le cache en mémoire par utilisateur
        self._initialize_cache()
        logger.info("PharmacyService initialisé")

    def _initialize_cache(self):
        """Initialiser le cache en mémoire dans st.session_state pour chaque utilisateur."""
        user_id = st.session_state.get("username", "default")
        if "app_state" not in st.session_state:
            st.session_state.app_state = {}
        if user_id not in st.session_state.app_state:
            st.session_state.app_state[user_id] = {}
        if "pharmacy_cache" not in st.session_state.app_state[user_id]:
            st.session_state.app_state[user_id]["pharmacy_cache"] = {}
        if "cache_expiration" not in st.session_state.app_state[user_id]:
            st.session_state.app_state[user_id]["cache_expiration"] = {}
        logger.info(f"Cache en mémoire initialisé pour l'utilisateur {user_id}")

    def _get_from_cache(self, cache_key: str) -> Tuple[Dict, bool]:
        """Récupérer les données du cache en mémoire si non expirées."""
        user_id = st.session_state.get("username", "default")
        cache = st.session_state.app_state[user_id].get("pharmacy_cache", {})
        expiration = st.session_state.app_state[user_id].get("cache_expiration", {})

        if cache_key in cache and cache_key in expiration:
            if expiration[cache_key] > datetime.now():
                logger.info(f"Cache hit pour la clé {cache_key}")
                return cache[cache_key], True
            else:
                # Supprimer les entrées expirées
                del cache[cache_key]
                del expiration[cache_key]
                st.session_state.app_state[user_id]["pharmacy_cache"] = cache
                st.session_state.app_state[user_id]["cache_expiration"] = expiration
                logger.info(f"Entrée de cache expirée supprimée pour la clé {cache_key}")
        return None, False

    def _store_in_cache(self, cache_key: str, data: Dict):
        """Stocker les données dans le cache avec une expiration de 24h."""
        user_id = st.session_state.get("username", "default")
        cache = st.session_state.app_state[user_id].get("pharmacy_cache", {})
        expiration = st.session_state.app_state[user_id].get("cache_expiration", {})

        cache[cache_key] = data
        expiration[cache_key] = datetime.now() + timedelta(hours=24)
        st.session_state.app_state[user_id]["pharmacy_cache"] = cache
        st.session_state.app_state[user_id]["cache_expiration"] = expiration
        logger.info(f"Données stockées dans le cache pour la clé {cache_key}, expiration dans 24h")

    def get_pharmacies_in_subarea(self, center_lat: float, center_lon: float, radius: float) -> Tuple[List[Dict], int]:
        """
        Récupérer les pharmacies dans une sous-zone via l'API Google Places.
        Utilise un cache en mémoire pour éviter les requêtes redondantes.

        Args:
            center_lat (float): Latitude du centre de la sous-zone.
            center_lon (float): Longitude du centre de la sous-zone.
            radius (float): Rayon de recherche en mètres.

        Returns:
            Tuple[List[Dict], int]: Liste des pharmacies et nombre de requêtes effectuées.
        """
        # Créer une clé unique pour le cache
        cache_key = f"pharmacy:{center_lat:.6f}:{center_lon:.6f}:{radius}"
        cached_data, cache_hit = self._get_from_cache(cache_key)
        if cache_hit:
            return cached_data, 0

        pharmacies = []
        request_count = 0
        url = "https://places.googleapis.com/v1/places:searchNearby"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "places.displayName,places.location,places.formattedAddress,nextPageToken"
        }
        payload = {
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": center_lat, "longitude": center_lon},
                    "radius": radius
                }
            },
            "includedTypes": ["pharmacy"],
            "maxResultCount": 20
        }

        try:
            # Première requête
            response = requests.post(url, json=payload, headers=headers)
            request_count += 1
            response.raise_for_status()
            data = response.json()
            places = data.get("places", [])
            for place in places:
                display_name = place.get("displayName", {}).get("text", "Unknown")
                location = place.get("location", {})
                latitude = location.get("latitude")
                longitude = location.get("longitude")
                # Valider les coordonnées
                if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                    logger.warning(f"Coordonnées invalides pour {display_name}: lat={latitude}, lon={longitude}")
                    continue
                pharmacies.append({
                    "name": display_name,
                    "address": place.get("formattedAddress", ""),
                    "latitude": latitude,
                    "longitude": longitude
                })

            # Gestion de la pagination
            next_page_token = data.get("nextPageToken")
            while next_page_token:
                time.sleep(2)  # Délai pour respecter les restrictions de l'API
                payload["pageToken"] = next_page_token
                response = requests.post(url, json=payload, headers=headers)
                request_count += 1
                response.raise_for_status()
                data = response.json()
                places = data.get("places", [])
                for place in places:
                    display_name = place.get("displayName", {}).get("text", "Unknown")
                    location = place.get("location", {})
                    latitude = location.get("latitude")
                    longitude = location.get("longitude")
                    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                        logger.warning(f"Coordonnées invalides pour {display_name}: lat={latitude}, lon={longitude}")
                        continue
                    pharmacies.append({
                        "name": display_name,
                        "address": place.get("formattedAddress", ""),
                        "latitude": latitude,
                        "longitude": longitude
                    })
                next_page_token = data.get("nextPageToken")

            # Supprimer les doublons
            unique_pharmacies = []
            seen = set()
            for pharmacy in pharmacies:
                key = (pharmacy["name"], pharmacy["latitude"], pharmacy["longitude"])
                if key not in seen:
                    seen.add(key)
                    unique_pharmacies.append(pharmacy)

            # Stocker dans le cache
            self._store_in_cache(cache_key, unique_pharmacies)
            logger.info(
                f"Récupéré {len(unique_pharmacies)} pharmacies pour sous-zone ({center_lat:.4f}, {center_lon:.4f})")
            return unique_pharmacies, request_count

        except requests.RequestException as e:
            logger.error(f"Erreur API Google Places pour sous-zone ({center_lat:.4f}, {center_lon:.4f}) : {e}")
            st.error(f"Erreur lors de la récupération des pharmacies : {e}")
            return [], request_count

    def get_pharmacies_in_area(self, lat_min: float, lat_max: float, lon_min: float, lon_max: float,
                               subarea_step: float, subarea_radius: float) -> Tuple[List[Dict], int]:
        """
        Récupérer les pharmacies dans une zone en divisant en sous-zones.

        Args:
            lat_min (float): Latitude minimale de la zone.
            lat_max (float): Latitude maximale de la zone.
            lon_min (float): Longitude minimale de la zone.
            lon_max (float): Longitude maximale de la zone.
            subarea_step (float): Pas pour diviser la zone en sous-zones.
            subarea_radius (float): Rayon des sous-zones en mètres.

        Returns:
            Tuple[List[Dict], int]: Liste des pharmacies et nombre total de requêtes.
        """
        # Validation des coordonnées
        if not (-90 <= lat_min <= 90 and -90 <= lat_max <= 90 and -180 <= lon_min <= 180 and -180 <= lon_max <= 180):
            logger.error(
                f"Coordonnées invalides : lat_min={lat_min}, lat_max={lat_max}, lon_min={lon_min}, lon_max={lon_max}")
            st.error("Erreur : coordonnées géographiques invalides.")
            return [], 0

        if lat_min >= lat_max or lon_min >= lon_max:
            logger.error(
                f"Ordre des coordonnées invalide : lat_min={lat_min}, lat_max={lat_max}, lon_min={lon_min}, lon_max={lon_max}")
            st.error("Erreur : les limites de la zone sont incorrectes.")
            return [], 0

        # Ajuster dynamiquement subarea_step et subarea_radius selon la densité
        area_km2 = ((lat_max - lat_min) * 111) * (
                    (lon_max - lon_min) * 111 * np.cos(np.radians((lat_min + lat_max) / 2)))
        if area_km2 < 1.0:  # Zones urbaines denses
            subarea_step = min(subarea_step, 0.005)  # Pas plus fin
            subarea_radius = min(subarea_radius, 500)  # Rayon réduit
        logger.info(f"Zone : area={area_km2:.2f} km², subarea_step={subarea_step}, subarea_radius={subarea_radius}")

        all_pharmacies = []
        total_requests = 0
        seen = set()
        user_id = st.session_state.get("username", "default")

        try:
            # Diviser la zone en sous-zones
            lat_steps = np.arange(lat_min, lat_max, subarea_step)
            lon_steps = np.arange(lon_min, lon_max, subarea_step)
            total_subareas = len(lat_steps) * len(lon_steps)
            logger.info(f"Exploration de {total_subareas} sous-zones")

            # Barre de progression pour l'utilisateur
            progress_bar = st.sidebar.progress(0)
            for i, (center_lat, center_lon) in enumerate(product(lat_steps, lon_steps)):
                pharmacies, requests = self.get_pharmacies_in_subarea(center_lat, center_lon, subarea_radius)
                total_requests += requests
                for pharmacy in pharmacies:
                    key = (pharmacy["name"], pharmacy["latitude"], pharmacy["longitude"])
                    if key not in seen:
                        seen.add(key)
                        all_pharmacies.append(pharmacy)
                # Mettre à jour la barre de progression
                progress_bar.progress((i + 1) / total_subareas)

            progress_bar.empty()
            logger.info(f"Total pharmacies trouvées : {len(all_pharmacies)}, requêtes : {total_requests}")
            return all_pharmacies, total_requests

        except Exception as e:
            logger.error(f"Erreur lors de la recherche dans la zone : {e}")
            st.error(f"Erreur lors de la recherche : {e}")
            return [], total_requests