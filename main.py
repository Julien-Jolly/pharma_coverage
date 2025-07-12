import streamlit as st
import folium
import numpy as np
import pandas as pd
import os
import json
from dotenv import load_dotenv
import requests
from streamlit_folium import st_folium
import time
import logging
from itertools import product
import hashlib

# Configurer les journaux pour la console PyCharm
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Charger les variables d'environnement
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    st.error("Erreur : la clé API Google n'est pas définie dans le fichier .env")
    logger.error("Clé API Google non définie dans .env")
    st.stop()

# Initialiser st.session_state
if 'page' not in st.session_state:
    st.session_state.page = "Sélection de la zone"
if 'search_in_progress' not in st.session_state:
    st.session_state.search_in_progress = False
if 'map' not in st.session_state:
    st.session_state.map = None
if 'map_center' not in st.session_state:
    st.session_state.map_center = {'lat': 33.5731, 'lng': -7.5898}
if 'map_zoom' not in st.session_state:
    st.session_state.map_zoom = 12
if 'search_history' not in st.session_state:
    st.session_state.search_history = []
if 'selected_pharmacies_key' not in st.session_state:
    st.session_state.selected_pharmacies_key = None
logger.info(
    f"Initialisation : page={st.session_state.page}, search_in_progress={st.session_state.search_in_progress}, map={'défini' if st.session_state.map else 'non défini'}, map_center={st.session_state.map_center}, map_zoom={st.session_state.map_zoom}, search_history={len(st.session_state.search_history)} recherches, selected_pharmacies_key={st.session_state.selected_pharmacies_key}")


# Fonction pour gérer le compteur global de requêtes
def update_request_count(requests):
    request_count_file = "request_count.json"
    try:
        if os.path.exists(request_count_file):
            with open(request_count_file, "r") as f:
                data = json.load(f)
                total_requests = data.get("total_requests", 0)
        else:
            total_requests = 0
        total_requests += requests
        with open(request_count_file, "w") as f:
            json.dump({"total_requests": total_requests}, f)
        logger.info(f"Compteur de requêtes mis à jour : {total_requests} requêtes")
        return total_requests
    except Exception as e:
        st.error(f"Erreur lors de la mise à jour du compteur de requêtes : {e}")
        logger.error(f"Erreur lors de la mise à jour du compteur de requêtes : {e}")
        return requests


def get_total_requests():
    request_count_file = "request_count.json"
    try:
        if os.path.exists(request_count_file):
            with open(request_count_file, "r") as f:
                data = json.load(f)
                return data.get("total_requests", 0)
        return 0
    except Exception as e:
        st.error(f"Erreur lors de la lecture du compteur de requêtes : {e}")
        logger.error(f"Erreur lors de la lecture du compteur de requêtes : {e}")
        return 0


# Fonction pour gérer l'historique des recherches
def load_search_history():
    search_history_file = "search_history.json"
    try:
        if os.path.exists(search_history_file):
            with open(search_history_file, "r") as f:
                st.session_state.search_history = json.load(f)
        else:
            st.session_state.search_history = []
        logger.info(f"Historique chargé : {len(st.session_state.search_history)} recherches")
    except Exception as e:
        st.error(f"Erreur lors du chargement de l'historique : {e}")
        logger.error(f"Erreur lors du chargement de l'historique : {e}")
        st.session_state.search_history = []


def save_search_history(search_data):
    search_history_file = "search_history.json"
    try:
        st.session_state.search_history.append(search_data)
        with open(search_history_file, "w") as f:
            json.dump(st.session_state.search_history, f)
        logger.info(f"Recherche enregistrée : {search_data['name']}")
    except Exception as e:
        st.error(f"Erreur lors de l'enregistrement de l'historique : {e}")
        logger.error(f"Erreur lors de l'enregistrement de l'historique : {e}")


# Fonction pour vérifier l'unicité du nom de la recherche
def is_search_name_unique(name):
    return not any(search["name"] == name for search in st.session_state.search_history)


# Fonction pour estimer une bounding box à partir du centre et du zoom
def estimate_bounds(center_lat, center_lon, zoom):
    delta = 0.05 / (2 ** (zoom - 12))
    lat_min = center_lat - delta
    lat_max = center_lat + delta
    lon_min = center_lon - delta
    lon_max = center_lon + delta
    logger.info(
        f"Estimation des limites : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, lon_min={lon_min:.4f}, lon_max={lon_max:.4f}")
    return lat_min, lat_max, lon_min, lon_max


# Fonction pour collecter les pharmacies dans une sous-zone
@st.cache_data
def get_pharmacies_in_subarea(center_lat, center_lon, radius):
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
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": "places.displayName,places.location"
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
            pharmacies.append({
                "name": name,
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
                pharmacies.append({
                    "name": name,
                    "latitude": lat,
                    "longitude": lon
                })
                logger.info(f"Pharmacie ajoutée : {name}, ({lat:.4f}, {lon:.4f})")
        st.write(f"Requête pour sous-zone ({center_lat:.4f}, {center_lon:.4f}) : {request_count} requêtes effectuées")
        logger.info(
            f"Sous-zone ({center_lat:.4f}, {center_lon:.4f}) : {len(pharmacies)} pharmacies trouvées, {request_count} requêtes")

    except requests.exceptions.RequestException as e:
        st.error(f"Erreur pour sous-zone ({center_lat:.4f}, {center_lon:.4f}) : {e}")
        logger.error(f"Erreur pour sous-zone ({center_lat:.4f}, {center_lon:.4f}) : {e}")
        if response.text:
            st.error(f"Détails de l'erreur : {response.text}")
            logger.error(f"Détails de l'erreur : {response.text}")

    return pharmacies, request_count


# Fonction pour collecter les pharmacies dans la bounding box
@st.cache_data
def get_pharmacies_in_area(lat_min, lat_max, lon_min, lon_max, subarea_step, subarea_radius):
    pharmacies = []
    total_requests = 0

    lat_points = np.arange(lat_min, lat_max, subarea_step)
    lon_points = np.arange(lon_min, lon_max, subarea_step)
    subarea_centers = list(product(lat_points, lon_points))

    st.write(f"Nombre de sous-zones à traiter : {len(subarea_centers)}")
    logger.info(f"Collecte des pharmacies pour {len(subarea_centers)} sous-zones")

    for center_lat, center_lon in subarea_centers:
        subarea_pharmacies, request_count = get_pharmacies_in_subarea(center_lat, center_lon, subarea_radius)
        pharmacies.extend(subarea_pharmacies)
        total_requests += request_count

    unique_pharmacies = []
    seen = set()
    for p in pharmacies:
        key = (p["latitude"], p["longitude"], p["name"])
        if key not in seen:
            seen.add(key)
            unique_pharmacies.append(p)

    st.write(f"Nombre total de requêtes effectuées pour la collecte des pharmacies : {total_requests}")
    logger.info(f"Collecte terminée : {len(unique_pharmacies)} pharmacies uniques, {total_requests} requêtes")
    update_request_count(total_requests)
    return unique_pharmacies, total_requests


# Créer une carte Folium avec cercles de 300m et popup au survol
def create_map(pharmacies, center_lat, center_lon, zoom, width=700, height=500):
    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom, width=width, height=height)
    for pharmacy in pharmacies:
        folium.Circle(
            location=[pharmacy['latitude'], pharmacy['longitude']],
            radius=300,
            color='green',
            fill=True,
            fill_color='green',
            fill_opacity=0.5,
            opacity=0.5,
            popup=pharmacy['name']
        ).add_to(m)
    logger.info(
        f"Carte créée : {len(pharmacies)} cercles de 300m avec popup, center=({center_lat:.4f}, {center_lon:.4f}), zoom={zoom}, width={width}, height={height}")
    return m


# Navigation via la barre latérale
st.sidebar.title("Navigation")
page = st.sidebar.selectbox("Choisir une page",
                            ["Sélection de la zone", "Résultats", "Facturation", "Historique des recherches"],
                            index=["Sélection de la zone", "Résultats", "Facturation",
                                   "Historique des recherches"].index(st.session_state.page))
if page != st.session_state.page:
    logger.info(f"Mise à jour de la page via la barre latérale : de {st.session_state.page} à {page}")
    st.session_state.page = page
    st.session_state.search_in_progress = False
    if page == "Sélection de la zone":
        st.session_state.map = None
        st.session_state.map_center = {'lat': 33.5731, 'lng': -7.5898}
        st.session_state.map_zoom = 12
        st.session_state.selected_pharmacies_key = None
        logger.info(
            "Réinitialisation pour la page Sélection de la zone : map=None, map_center et map_zoom réinitialisés, selected_pharmacies_key=None")

# Charger l'historique des recherches au démarrage
load_search_history()

# Page 1 : Sélection de la zone
if st.session_state.page == "Sélection de la zone":
    st.header("Sélection de la zone de recherche")

    st.write("Ajustez la carte (zoom/déplacement) pour définir la zone visible à l’écran.")
    m = folium.Map(location=[33.5731, -7.5898], zoom_start=12)  # Centre sur Casablanca

    map_data = st_folium(m, width=700, height=500)
    logger.info(f"Données de la carte : {map_data}")

    # Champ pour nommer la recherche
    search_name = st.text_input("Nom de la recherche", placeholder="Entrez un nom unique pour la recherche")

    # Bouton pour valider la zone
    if st.button("Valider la zone"):
        lat_min, lat_max, lon_min, lon_max = None, None, None, None
        if "bounds" in map_data and map_data["bounds"]:
            try:
                bounds = map_data["bounds"]
                lat_min = bounds["_southWest"]["lat"]
                lat_max = bounds["_northEast"]["lat"]
                lon_min = bounds["_southWest"]["lng"]
                lon_max = bounds["_northEast"]["lng"]
                if lat_min < lat_max and lon_min < lon_max:
                    st.session_state.bounds = (lat_min, lat_max, lon_min, lon_max)
                    st.write(
                        f"Zone validée : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, lon_min={lon_min:.4f}, lon_max={lon_max:.4f}")
                    logger.info(
                        f"Zone validée : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, lon_min={lon_min:.4f}, lon_max={lon_max:.4f}")
                    st.session_state.search_in_progress = False
                else:
                    st.error("Erreur : les coordonnées de la zone sont invalides.")
                    logger.error("Coordonnées de la zone invalides")
            except (KeyError, TypeError) as e:
                # Fallback : estimer la bounding box
                logger.warning(f"Erreur lors de la récupération des limites : {e}")
                center = map_data.get("center", {"lat": 33.5731, "lng": -7.5898})
                zoom = map_data.get("zoom", 12)
                lat_min, lat_max, lon_min, lon_max = estimate_bounds(center["lat"], center["lng"], zoom)
                if lat_min < lat_max and lon_min < lon_max:
                    st.session_state.bounds = (lat_min, lat_max, lon_min, lon_max)
                    st.write(
                        f"Zone validée (estimée) : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, lon_min={lon_min:.4f}, lon_max={lon_max:.4f}")
                    logger.info(
                        f"Zone validée (estimée) : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, lon_min={lon_min:.4f}, lon_max={lon_max:.4f}")
                    st.session_state.search_in_progress = False
                else:
                    st.error("Erreur : les coordonnées estimées de la zone sont invalides.")
                    logger.error("Coordonnées estimées de la zone invalides")
        else:
            st.error(
                "Erreur : impossible de récupérer la zone visible. Ajustez la carte (zoom/déplacement) et réessayez.")
            logger.error("Impossible de récupérer la zone visible")

    # Afficher la section de recherche si la zone est validée
    if "bounds" in st.session_state:
        lat_min, lat_max, lon_min, lon_max = st.session_state.bounds
        if lat_min < lat_max and lon_min < lon_max:
            logger.info("Affichage de la section de recherche")
            st.subheader("Type de recherche")
            search_type = st.radio("Choisir le type de recherche",
                                   ["Recherche rapide (moins de requêtes)", "Recherche avancée (grille fine)"], index=0)
            subarea_step = 0.01 if "rapide" in search_type.lower() else 0.005
            subarea_radius = 1000 if "rapide" in search_type.lower() else 500

            # Calculer l'estimation des requêtes
            lat_points = np.arange(lat_min, lat_max, subarea_step)
            lon_points = np.arange(lon_min, lon_max, subarea_step)
            estimated_subareas = len(list(product(lat_points, lon_points)))
            st.warning(
                f"Cette recherche peut générer ~{estimated_subareas} requêtes, coût estimé : {estimated_subareas * 0.032:.2f}$")
            logger.info(f"Estimation : {estimated_subareas} sous-zones, coût ~{estimated_subareas * 0.032:.2f}$")

            if st.button("Lancer la recherche"):
                if not search_name:
                    st.error("Erreur : veuillez entrer un nom pour la recherche.")
                    logger.error("Nom de recherche vide")
                elif not is_search_name_unique(search_name):
                    st.error(f"Erreur : le nom '{search_name}' est déjà utilisé. Choisissez un autre nom.")
                    logger.error(f"Nom de recherche '{search_name}' déjà utilisé")
                else:
                    logger.info(
                        f"Lancement de la recherche : name={search_name}, type={search_type}, subarea_step={subarea_step}, subarea_radius={subarea_radius}")
                    try:
                        st.session_state.search_name = search_name
                        st.session_state.search_type = "quick" if "rapide" in search_type.lower() else "advanced"
                        st.session_state.subarea_step = subarea_step
                        st.session_state.subarea_radius = subarea_radius
                        st.session_state.search_in_progress = True
                        st.write("Recherche en cours...")
                        logger.info(
                            f"st.session_state mis à jour : page=Résultats, search_name={search_name}, search_type={st.session_state.search_type}, search_in_progress=True")

                        # Lancer la recherche directement
                        pharmacies, total_requests = get_pharmacies_in_area(lat_min, lat_max, lon_min, lon_max,
                                                                            subarea_step, subarea_radius)
                        if not pharmacies:
                            st.error("Aucune pharmacie trouvée. Vérifiez votre clé API ou la zone.")
                            logger.error("Aucune pharmacie trouvée")
                            st.write("Vérifiez sur https://www.google.com/maps en recherchant 'pharmacy'.")
                            st.session_state.search_in_progress = False
                            st.session_state.page = "Sélection de la zone"
                            st.session_state.map = None
                            st.session_state.selected_pharmacies_key = None
                        else:
                            st.session_state.pharmacies = pharmacies
                            st.session_state.total_requests = total_requests
                            # Générer la carte initiale
                            center_lat = (lat_min + lat_max) / 2
                            center_lon = (lon_min + lon_max) / 2
                            st.session_state.map = create_map(pharmacies, center_lat, center_lon,
                                                              st.session_state.map_zoom)
                            st.session_state.map_center = {'lat': center_lat, 'lng': center_lon}
                            st.session_state.selected_pharmacies = pharmacies
                            st.session_state.selected_pharmacies_key = hashlib.md5(
                                str([(p['latitude'], p['longitude'], p['name']) for p in
                                     pharmacies]).encode()).hexdigest()
                            # Enregistrer la recherche dans l'historique
                            search_data = {
                                "name": search_name,
                                "bounds": st.session_state.bounds,
                                "search_type": st.session_state.search_type,
                                "subarea_step": subarea_step,
                                "subarea_radius": subarea_radius,
                                "pharmacies": pharmacies,
                                "total_requests": total_requests,
                                "map_html": st.session_state.map._repr_html_(),
                                "center_lat": center_lat,
                                "center_lon": center_lon,
                                "zoom": st.session_state.map_zoom
                            }
                            save_search_history(search_data)
                            st.session_state.search_in_progress = False
                            st.session_state.page = "Résultats"
                            logger.info(
                                f"Recherche terminée : {len(pharmacies)} pharmacies trouvées, {total_requests} requêtes effectuées, carte initiale générée avec {len(pharmacies)} cercles, recherche enregistrée sous '{search_name}', selected_pharmacies_key={st.session_state.selected_pharmacies_key}")
                    except Exception as e:
                        st.error(f"Erreur lors du lancement de la recherche : {e}")
                        logger.error(f"Erreur lors du lancement de la recherche : {e}")
                        st.session_state.search_in_progress = False
                        st.session_state.page = "Sélection de la zone"
                        st.session_state.map = None
                        st.session_state.selected_pharmacies_key = None
        else:
            st.error("Erreur : les coordonnées de la bounding box sont invalides. Veuillez valider une nouvelle zone.")
            logger.error("Coordonnées de la bounding box invalides")
            st.session_state.search_in_progress = False
            st.session_state.map = None
            st.session_state.selected_pharmacies_key = None
    else:
        logger.info("Section de recherche non affichée : bounds non défini")
        if st.button("Réinitialiser l'état (si la section de recherche n'apparaît pas)"):
            st.session_state.search_in_progress = False
            st.session_state.map = None
            st.session_state.selected_pharmacies_key = None
            logger.info("État réinitialisé : search_in_progress=False, map=None, selected_pharmacies_key=None")

# Page 2 : Résultats
elif st.session_state.page == "Résultats":
    st.header("Résultats de la recherche")
    logger.info("Affichage de la page Résultats")

    if "bounds" not in st.session_state or "search_type" not in st.session_state or "pharmacies" not in st.session_state:
        st.error("Aucune zone sélectionnée, type de recherche ou résultats définis. Retournez à la page de sélection.")
        logger.error("Aucune zone, type de recherche ou résultats définis")
        st.session_state.page = "Sélection de la zone"
        st.session_state.search_in_progress = False
        st.session_state.map = None
        st.session_state.selected_pharmacies_key = None
        st.stop()

    lat_min, lat_max, lon_min, lon_max = st.session_state.bounds
    subarea_step = st.session_state.subarea_step
    subarea_radius = st.session_state.subarea_radius
    pharmacies = st.session_state.pharmacies
    total_requests = st.session_state.total_requests
    search_name = st.session_state.get("search_name", "Recherche sans nom")
    logger.info(
        f"Paramètres de recherche : name={search_name}, lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, lon_min={lon_min:.4f}, lon_max={lon_max:.4f}, step={subarea_step}, radius={subarea_radius}")
    logger.info(f"Résultats : {len(pharmacies)} pharmacies trouvées, {total_requests} requêtes effectuées")

    # Afficher la carte en haut
    with st.container():
        if st.session_state.map is None:
            # Régénérer la carte initiale si nécessaire
            center_lat = st.session_state.map_center['lat']
            center_lon = st.session_state.map_center['lng']
            selected_pharmacies = st.session_state.get("selected_pharmacies", pharmacies)
            st.session_state.map = create_map(selected_pharmacies, center_lat, center_lon, st.session_state.map_zoom)
            st.session_state.selected_pharmacies_key = hashlib.md5(
                str([(p['latitude'], p['longitude'], p['name']) for p in selected_pharmacies]).encode()).hexdigest()
            logger.info(
                f"Carte régénérée : {len(selected_pharmacies)} cercles, selected_pharmacies_key={st.session_state.selected_pharmacies_key}")

        # Afficher la carte uniquement si la clé n'a pas changé
        if st.session_state.selected_pharmacies_key:
            logger.info(
                f"Affichage de la carte avec selected_pharmacies_key={st.session_state.selected_pharmacies_key}")
            map_data = st_folium(st.session_state.map, width=700, height=500,
                                 key=f"results_map_{st.session_state.selected_pharmacies_key}")
            if map_data and "center" in map_data and "zoom" in map_data and map_data["center"] and map_data["zoom"]:
                st.session_state.map_center = map_data["center"]
                st.session_state.map_zoom = map_data["zoom"]
                logger.info(
                    f"Interaction avec la carte : mise à jour map_center={st.session_state.map_center}, map_zoom={st.session_state.map_zoom}, aucune régénération de la carte")
        else:
            logger.info("Carte non affichée : selected_pharmacies_key non défini")

    # Afficher les statistiques
    st.write(f"Nom de la recherche : {search_name}")
    st.write(f"Nombre total de pharmacies trouvées : {len(pharmacies)}")
    st.write(f"Nombre total de requêtes effectuées pour cette recherche : {total_requests}")

    # Liste des pharmacies dans un conteneur déroulant
    with st.expander("Pharmacies trouvées", expanded=False):
        # Ajouter du CSS pour limiter la hauteur et activer le défilement
        st.markdown(
            """
            <style>
            .pharmacy-list {
                max-height: 300px;
                overflow-y: auto;
                padding: 10px;
                border: 1px solid #ccc;
                border-radius: 5px;
            }
            </style>
            """,
            unsafe_allow_html=True
        )
        with st.container():
            st.markdown('<div class="pharmacy-list">', unsafe_allow_html=True)
            selected_pharmacies = []
            for i, pharmacy in enumerate(pharmacies):
                if st.checkbox(pharmacy['name'], key=f"pharmacy_{i}", value=True):
                    selected_pharmacies.append(pharmacy)
            st.markdown('</div>', unsafe_allow_html=True)

    # Bouton pour recalculer
    if st.button("Recalculer"):
        st.session_state.selected_pharmacies = selected_pharmacies
        # Mettre à jour la clé des pharmacies sélectionnées
        st.session_state.selected_pharmacies_key = hashlib.md5(
            str([(p['latitude'], p['longitude'], p['name']) for p in selected_pharmacies]).encode()).hexdigest()
        # Régénérer la carte avec les pharmacies sélectionnées
        center_lat = st.session_state.map_center['lat']
        center_lon = st.session_state.map_center['lng']
        st.session_state.map = create_map(selected_pharmacies, center_lat, center_lon, st.session_state.map_zoom)
        logger.info(
            f"Carte mise à jour après recalcul : {len(selected_pharmacies)} cercles, selected_pharmacies_key={st.session_state.selected_pharmacies_key}")

    # Téléchargement des résultats
    df_pharmacies = pd.DataFrame(pharmacies)
    csv = df_pharmacies.to_csv(index=False)
    st.download_button(
        label="Télécharger la liste des pharmacies (CSV)",
        data=csv,
        file_name=f"pharmacies_{search_name}.csv",
        mime="text/csv"
    )
    map_html = st.session_state.map._repr_html_() if st.session_state.map else ""
    st.download_button(
        label="Télécharger la carte (HTML)",
        data=map_html,
        file_name=f"pharmacy_coverage_map_{search_name}.html",
        mime="text/html",
        disabled=not st.session_state.map
    )

# Page 3 : Facturation
elif st.session_state.page == "Facturation":
    st.header("Facturation")
    total_requests = get_total_requests()
    st.write(f"Nombre total de requêtes effectuées (toutes sessions) : {total_requests}")
    st.write(f"Coût total estimé : {total_requests * 0.032:.2f}$")
    st.info("Ce coût est couvert par le crédit mensuel de 200$ de Google Maps Platform.")
    logger.info(f"Page Facturation : {total_requests} requêtes totales, coût estimé {total_requests * 0.032:.2f}$")

# Page 4 : Historique des recherches
elif st.session_state.page == "Historique des recherches":
    st.header("Historique des recherches")
    logger.info("Affichage de la page Historique des recherches")

    if not st.session_state.search_history:
        st.info("Aucun historique de recherche disponible.")
        logger.info("Aucun historique de recherche")
    else:
        for search in st.session_state.search_history:
            st.subheader(f"Recherche : {search['name']}")
            # Générer une miniature de la carte
            mini_map = create_map(search["pharmacies"], search["center_lat"], search["center_lon"], search["zoom"],
                                  width=300, height=200)
            st_folium(mini_map, width=300, height=200, key=f"mini_map_{search['name']}")
            # Boutons pour visualiser ou télécharger
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("Visualiser", key=f"view_{search['name']}"):
                    st.session_state.bounds = search["bounds"]
                    st.session_state.search_type = search["search_type"]
                    st.session_state.subarea_step = search["subarea_step"]
                    st.session_state.subarea_radius = search["subarea_radius"]
                    st.session_state.pharmacies = search["pharmacies"]
                    st.session_state.total_requests = search["total_requests"]
                    st.session_state.search_name = search["name"]
                    st.session_state.map = create_map(search["pharmacies"], search["center_lat"], search["center_lon"],
                                                      search["zoom"])
                    st.session_state.map_center = {'lat': search["center_lat"], 'lng': search["center_lon"]}
                    st.session_state.map_zoom = search["zoom"]
                    st.session_state.selected_pharmacies = search["pharmacies"]
                    st.session_state.selected_pharmacies_key = hashlib.md5(
                        str([(p['latitude'], p['longitude'], p['name']) for p in
                             search["pharmacies"]]).encode()).hexdigest()
                    st.session_state.page = "Résultats"
                    logger.info(
                        f"Visualisation de la recherche '{search['name']}' : passage à la page Résultats, selected_pharmacies_key={st.session_state.selected_pharmacies_key}")
            with col2:
                df = pd.DataFrame(search["pharmacies"])
                csv = df.to_csv(index=False)
                st.download_button(
                    label="Télécharger CSV",
                    data=csv,
                    file_name=f"pharmacies_{search['name']}.csv",
                    mime="text/csv",
                    key=f"csv_{search['name']}"
                )
            with col3:
                st.download_button(
                    label="Télécharger HTML",
                    data=search["map_html"],
                    file_name=f"pharmacy_coverage_map_{search['name']}.html",
                    mime="text/html",
                    key=f"html_{search['name']}"
                )