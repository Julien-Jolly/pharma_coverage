import streamlit as st
import folium
import pandas as pd
from itertools import product
from streamlit_folium import st_folium
import numpy as np
import logging
from utils.helpers import estimate_bounds, generate_pharmacies_key, get_bounds_key, generate_subzone_key
from geopy.geocoders import Nominatim

logger = logging.getLogger(__name__)

# Constantes
DEFAULT_CENTER = {'lat': 33.5731, 'lng': -7.5898}  # Casablanca
DEFAULT_ZOOM = 12
CIRCLE_RADIUS = 300
CIRCLE_OPACITY = 0.5
MAP_WIDTH = "100%"
MAP_HEIGHT = 600
MINI_MAP_WIDTH = 300
MINI_MAP_HEIGHT = 200
MAX_AREA_KM2 = 4.0


def _geocode_location(location):
    try:
        geolocator = Nominatim(user_agent="pharmacy_coverage_app")
        location_data = geolocator.geocode(location)
        if location_data:
            return {'lat': location_data.latitude, 'lng': location_data.longitude}
        return None
    except Exception as e:
        logger.error(f"Erreur de géocodage pour {location} : {e}")
        return None


def _create_map(pharmacies, center_lat, center_lon, zoom, width=MAP_WIDTH, height=MAP_HEIGHT, selected_pharmacies=None, subzones=None):
    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom, width=width, height=height)
    selected_pharmacies = selected_pharmacies or []

    for pharmacy in pharmacies:
        is_selected = any(
            p['name'] == pharmacy['name'] and p['latitude'] == pharmacy['latitude'] and p['longitude'] == pharmacy['longitude']
            for p in selected_pharmacies
        )
        folium.Circle(
            location=[pharmacy['latitude'], pharmacy['longitude']],
            radius=CIRCLE_RADIUS,
            color='green',
            fill=is_selected,
            fill_color='green' if is_selected else None,
            fill_opacity=CIRCLE_OPACITY if is_selected else 0,
            opacity=CIRCLE_OPACITY,
            popup=pharmacy['name']
        ).add_to(m)

    if subzones:
        for sz in subzones:
            bounds = [
                [sz["lat_min"], sz["lon_min"]],
                [sz["lat_max"], sz["lon_max"]]
            ]
            folium.Rectangle(
                bounds=bounds,
                color="gray",
                fill=False,
                weight=1,
                tooltip=f"Sous-zone : {sz.get('key', '')}"
            ).add_to(m)

    logger.info(f"Carte créée : {len(pharmacies)} cercles, {len(subzones or [])} rectangles de sous-zones")
    return m


def _calculate_area_km2(lat_min, lat_max, lon_min, lon_max):
    lat_km = (lat_max - lat_min) * 111
    lon_km = (lon_max - lon_min) * 111 * np.cos(np.radians((lat_min + lat_max) / 2))
    return lat_km * lon_km


def _process_search(app, lat_min, lat_max, lon_min, lon_max, subarea_step, subarea_radius, search_name, user_id):
    logger.info(f"Lancement de la recherche : name={search_name}, user_id={user_id}, step={subarea_step}, radius={subarea_radius}")
    try:
        bounds = (lat_min, lat_max, lon_min, lon_max)
        bounds_key = get_bounds_key(bounds)
        st.session_state.search_name = search_name
        st.session_state.search_type = "quick"
        st.session_state.subarea_step = subarea_step
        st.session_state.subarea_radius = subarea_radius
        st.session_state.search_in_progress = True

        # Message minimal pendant le process
        st.sidebar.write("Recherche en cours…")

        pharmacies, total_requests = app.pharmacy_service.get_pharmacies_in_area(
            lat_min, lat_max, lon_min, lon_max, subarea_step, subarea_radius, app.storage_service
        )

        if not pharmacies:
            st.sidebar.error("Aucune pharmacie trouvée. Vérifiez votre clé API ou la zone.")
            logger.error("Aucune pharmacie trouvée")
            _reset_search()
            return

        center_lat = (lat_min + lat_max) / 2
        center_lon = (lon_min + lon_max) / 2

        st.session_state.pharmacies = pharmacies
        st.session_state.total_requests = total_requests
        st.session_state.selected_pharmacies = pharmacies
        st.session_state.selected_pharmacies_key = generate_pharmacies_key(pharmacies)

        # Grille (pour affichage éventuel de la maille)
        st.session_state.subzones_display = [
            {
                "lat_min": sz_lat,
                "lat_max": sz_lat + subarea_step,
                "lon_min": sz_lon,
                "lon_max": sz_lon + subarea_step,
                "key": generate_subzone_key(sz_lat, sz_lon, subarea_radius)
            }
            for sz_lat, sz_lon in product(
                np.arange(lat_min, lat_max, subarea_step),
                np.arange(lon_min, lon_max, subarea_step)
            )
        ]

        # ✅ Mémoriser les sous-zones de la GRILLE (et pas depuis les pharmacies)
        grid_subzones = [
            generate_subzone_key(sz_lat, sz_lon, subarea_radius)
            for sz_lat in np.arange(lat_min, lat_max, subarea_step)
            for sz_lon in np.arange(lon_min, lon_max, subarea_step)
        ]
        st.session_state.last_subzones_used = list(dict.fromkeys(grid_subzones))  # dé-duplication + ordre stable

        st.session_state.map = _create_map(
            pharmacies, center_lat, center_lon, st.session_state.map_zoom,
            selected_pharmacies=st.session_state.selected_pharmacies,
            subzones=st.session_state.subzones_display
        )
        st.session_state.map_center = {'lat': center_lat, 'lng': center_lon}

        search_data = {
            "name": search_name,
            "user_id": user_id,
            "bounds": bounds,
            "bounds_hash": bounds_key,
            "search_type": st.session_state.search_type,
            "subarea_step": subarea_step,
            "subarea_radius": subarea_radius,
            "subzones_used": st.session_state.last_subzones_used,  # ✅ bonnes clés
            "total_requests": total_requests,
            "map_html": st.session_state.map._repr_html_() if hasattr(st.session_state.map, "_repr_html_") else "",
            "center_lat": center_lat,
            "center_lon": center_lon,
            "zoom": st.session_state.map_zoom
        }

        app.storage_service.save_search_history(search_data)

        if not st.session_state.is_admin:
            current_credits = app.user_service.get_user_credits(user_id)
            if current_credits >= 1:
                app.user_service.update_credits(user_id, current_credits - 1)
            else:
                st.sidebar.error("Erreur : crédits insuffisants pour cette recherche.")
                logger.error(f"Crédits insuffisants pour {user_id}")
                _reset_search()
                return

        if total_requests > 0:
            app.storage_service.increment_total_requests(user_id, total_requests)

        st.session_state.search_history = app.storage_service.load_search_history(user_id) if not st.session_state.is_admin else app.storage_service.load_search_history()
        st.session_state.search_in_progress = False
        st.session_state.page = "Résultats"
        logger.info(f"Recherche terminée : {len(pharmacies)} pharmacies")
    except Exception as e:
        st.sidebar.error(f"Erreur lors du lancement de la recherche : {e}")
        logger.error(f"Erreur dans _process_search : {e}")
        _reset_search()


def _reset_search():
    st.session_state.search_in_progress = False
    st.session_state.page = "Sélection de la zone"
    st.session_state.map = None
    st.session_state.selected_pharmacies_key = None
    st.session_state.selected_pharmacies = []
    st.session_state.pharmacies = []
    st.session_state.search_name = None
    st.session_state.search_type = None
    st.session_state.subarea_step = None
    st.session_state.subarea_radius = None
    st.session_state.total_requests = 0
    st.session_state.zone_validated = False
    logger.info("État réinitialisé")


def render_login_page(app):
    with st.container():
        st.header("Connexion")
        login_type = st.radio("Type de connexion", ["Utilisateur", "Administrateur"], index=0)
        if login_type == "Utilisateur":
            username = st.text_input("Nom d'utilisateur")
            password = st.text_input("Mot de passe", type="password")
            if st.button("Se connecter"):
                if app.user_service.authenticate_user(username, password):
                    credits = app.user_service.get_user_credits(username)
                    if credits is not None:
                        st.session_state.is_authenticated = True
                        st.session_state.is_admin = False
                        st.session_state.username = username
                        st.session_state.search_history = app.storage_service.load_search_history(username)
                        st.session_state.page = "Sélection de la zone"
                        app._reset_map_state()
                        st.success(f"Connexion réussie ! Crédits disponibles : {credits}")
                        logger.info(f"Connexion utilisateur {username} réussie, crédits : {credits}")
                        st.rerun()
                    else:
                        st.error("Erreur : utilisateur non trouvé.")
                        logger.warning(f"Utilisateur {username} non trouvé")
                else:
                    st.error("Nom d'utilisateur ou mot de passe incorrect.")
                    logger.warning(f"Échec de la connexion pour l'utilisateur {username}")
        else:
            password = st.text_input("Mot de passe administrateur", type="password")
            if st.button("Se connecter"):
                if app.user_service.authenticate_admin(password):
                    st.session_state.is_authenticated = True
                    st.session_state.is_admin = True
                    st.session_state.username = "admin"
                    st.session_state.search_history = app.storage_service.load_search_history()
                    st.session_state.page = "Sélection de la zone"
                    app._reset_map_state()
                    st.success("Connexion administrateur réussie !")
                    logger.info("Connexion administrateur réussie")
                    st.rerun()
                else:
                    st.error("Mot de passe administrateur incorrect.")
                    logger.warning("Échec de la connexion administrateur")


def render_selection_page(app):
    with st.container():
        st.header("Sélection de la zone de recherche")
        with st.sidebar:
            st.markdown("### Recherche de zone")
            if not st.session_state.is_admin:
                credits = app.user_service.get_user_credits(st.session_state.username)
                st.write(f"**Crédits disponibles** : {credits}")
            st.markdown("Ajustez la carte pour définir une zone de recherche (max 4 km² pour les utilisateurs non-admin).")
            st.markdown("<hr>", unsafe_allow_html=True)

            location = st.text_input("Rechercher une localité", placeholder="Ex. Casablanca, Maroc")
            if st.button("Rechercher"):
                if location:
                    logger.info(f"Recherche de localité : {location}")
                    coords = _geocode_location(location)
                    if coords and 'lat' in coords and 'lng' in coords:
                        st.session_state.map_center = {'lat': coords['lat'], 'lng': coords['lng']}
                        st.session_state.map_zoom = DEFAULT_ZOOM
                        st.session_state.map = None
                        logger.info(f"Localité trouvée : center={st.session_state.map_center}, zoom={st.session_state.map_zoom}")
                        st.rerun()
                    else:
                        st.error("Localité non trouvée. Vérifiez l'orthographe ou essayez une autre adresse.")
                        logger.error(f"Échec de géocodage pour : {location}")
            st.markdown("<hr>", unsafe_allow_html=True)

            st.markdown("### Paramètres de recherche")
            search_name = st.text_input("Nom de la recherche", placeholder="Entrez un nom unique pour la recherche")
            if search_name and not app.storage_service.is_search_name_unique(search_name, st.session_state.username):
                st.error("Erreur : ce nom de recherche existe déjà. Choisissez un nom unique.")
                logger.warning(f"Nom de recherche non unique : {search_name} pour {st.session_state.username}")

        if st.session_state.map is None:
            st.session_state.map = folium.Map(
                location=[st.session_state.map_center['lat'], st.session_state.map_center['lng']],
                zoom_start=st.session_state.map_zoom,
                width=MAP_WIDTH,
                height=MAP_HEIGHT
            )
            logger.info(f"Carte initialisée pour Sélection : center={st.session_state.map_center}, zoom={st.session_state.map_zoom}")

        map_data = st_folium(st.session_state.map, width=MAP_WIDTH, height=MAP_HEIGHT, key="selection_map")

        if map_data and isinstance(map_data, dict) and "center" in map_data and "zoom" in map_data and map_data["center"]:
            st.session_state.map_center = map_data["center"]
            st.session_state.map_zoom = map_data["zoom"]
            logger.info(f"Interaction avec la carte : map_center={st.session_state.map_center}, zoom={st.session_state.map_zoom}")

        with st.sidebar:
            if st.button("Valider la zone"):
                logger.info("Clic sur Valider la zone")
                lat_min, lat_max, lon_min, lon_max = None, None, None, None
                if map_data and isinstance(map_data, dict) and "bounds" in map_data and map_data["bounds"]:
                    try:
                        bounds = map_data["bounds"]
                        lat_min = bounds["_southWest"]["lat"]
                        lat_max = bounds["_northEast"]["lat"]
                        lon_min = bounds["_southWest"]["lng"]
                        lon_max = bounds["_northEast"]["lng"]
                        if lat_min < lat_max and lon_min < lon_max:
                            area_km2 = _calculate_area_km2(lat_min, lat_max, lon_min, lon_max)
                            if not st.session_state.is_admin and area_km2 > MAX_AREA_KM2:
                                st.error(f"Erreur : la zone est trop grande ({area_km2:.2f} km²). Limitez à {MAX_AREA_KM2} km².")
                                logger.error(f"Zone trop grande : {area_km2:.2f} km²")
                                st.session_state.zone_validated = False
                            else:
                                st.session_state.bounds = (lat_min, lat_max, lon_min, lon_max)
                                st.session_state.zone_validated = True
                                st.write(f"Zone validée : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, "
                                         f"lon_min={lon_min:.4f}, lon_max={lon_max:.4f} ({area_km2:.2f} km²)")
                                logger.info(f"Zone validée : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, "
                                            f"lon_min={lon_min:.4f}, lon_max={lon_max:.4f}, area={area_km2:.2f} km²")
                        else:
                            st.error("Erreur : les coordonnées de la zone sont invalides.")
                            logger.error("Coordonnées de la zone invalides")
                            st.session_state.zone_validated = False
                    except (KeyError, TypeError) as e:
                        logger.warning(f"Erreur lors de la récupération des limites : {e}")
                        center = map_data.get("center", st.session_state.map_center)
                        zoom = map_data.get("zoom", st.session_state.map_zoom)
                        lat_min, lat_max, lon_min, lon_max = estimate_bounds(center["lat"], center["lng"], zoom)
                        area_km2 = _calculate_area_km2(lat_min, lat_max, lon_min, lon_max)  # ✅ ordre correct
                        if not st.session_state.is_admin and area_km2 > MAX_AREA_KM2:
                            st.error(f"Erreur : la zone estimée est trop grande ({area_km2:.2f} km²). Limitez à {MAX_AREA_KM2} km².")
                            logger.error(f"Zone estimée trop grande : {area_km2:.2f} km²")
                            st.session_state.zone_validated = False
                        else:
                            st.session_state.bounds = (lat_min, lat_max, lon_min, lon_max)
                            st.session_state.zone_validated = True
                            st.write(f"Zone validée (estimée) : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, "
                                     f"lon_min={lon_min:.4f}, lon_max={lon_max:.4f} ({area_km2:.2f} km²)")
                            logger.info(f"Zone validée (estimée) : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, "
                                        f"lon_min={lon_min:.4f}, lon_max={lon_max:.4f}")
                else:
                    center = st.session_state.map_center
                    zoom = st.session_state.map_zoom
                    lat_min, lat_max, lon_min, lon_max = estimate_bounds(center["lat"], center["lng"], zoom)
                    area_km2 = _calculate_area_km2(lat_min, lat_max, lon_min, lon_max)
                    if not st.session_state.is_admin and area_km2 > MAX_AREA_KM2:
                        st.error(f"Erreur : la zone estimée est trop grande ({area_km2:.2f} km²). Limitez à {MAX_AREA_KM2} km².")
                        logger.error(f"Zone estimée trop grande : {area_km2:.2f} km²")
                        st.session_state.zone_validated = False
                    else:
                        st.session_state.bounds = (lat_min, lat_max, lon_min, lon_max)
                        st.session_state.zone_validated = True
                        st.write(f"Zone validée (estimée) : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, "
                                 f"lon_min={lon_min:.4f}, lon_max={lon_max:.4f} ({area_km2:.2f} km²)")
                        logger.info(f"Zone validée (estimée) : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, "
                                    f"lon_min={lon_min:.4f}, lon_max={lon_max:.4f}")
                st.rerun()

            if st.session_state.zone_validated and st.session_state.bounds:
                lat_min, lat_max, lon_min, lon_max = st.session_state.bounds
                if lat_min < lat_max and lon_min < lon_max:
                    subarea_step = 0.01
                    subarea_radius = 1000
                    # Pas d'estimation ni coût, juste le bouton
                    if st.button(
                        "Lancer la recherche",
                        disabled=(
                            not search_name
                            or not app.storage_service.is_search_name_unique(search_name, st.session_state.username)
                            or (not st.session_state.is_admin and app.user_service.get_user_credits(st.session_state.username) < 1)
                        )
                    ):
                        logger.info("Clic sur Lancer la recherche")
                        _process_search(app, lat_min, lat_max, lon_min, lon_max, subarea_step, subarea_radius, search_name, st.session_state.username)
                        st.rerun()


def render_results_page(app):
    with st.container():
        st.header("Résultats de la recherche")
        logger.info("Affichage de la page Résultats")

        # Données minimales requises
        if not st.session_state.get("search_name") or not st.session_state.get("bounds"):
            st.sidebar.error("Aucune recherche récente disponible. Retournez à la page de sélection pour lancer une recherche.")
            logger.error("Données minimales manquantes (search_name/bounds)")
            st.session_state.page = "Sélection de la zone"
            app._reset_map_state()
            st.rerun()
            return

        lat_min, lat_max, lon_min, lon_max = st.session_state.bounds
        search_name = st.session_state.search_name

        # Reconstruire pharmacies si besoin depuis les subzones mémorisées
        if (not st.session_state.get("pharmacies")) and st.session_state.get("last_subzones_used"):
            rebuilt = app.storage_service.get_pharmacies_from_subzones(st.session_state["last_subzones_used"])
            st.session_state.pharmacies = rebuilt
            if not st.session_state.get("selected_pharmacies"):
                st.session_state.selected_pharmacies = rebuilt
            st.session_state.selected_pharmacies_key = generate_pharmacies_key(st.session_state.selected_pharmacies or [])

        # Reconstituer map_center si besoin
        if (not st.session_state.get("map_center")) or ('lat' not in st.session_state.get("map_center", {})) or ('lng' not in st.session_state.get("map_center", {})):
            center_lat = (lat_min + lat_max) / 2
            center_lon = (lon_min + lon_max) / 2
            st.session_state.map_center = {'lat': center_lat, 'lng': center_lon}
            if not st.session_state.get("map_zoom"):
                st.session_state.map_zoom = DEFAULT_ZOOM

        with st.sidebar:
            st.markdown("### Résultats de la recherche")
            st.write(f"**Nom de la recherche** : {search_name}")
            st.write(f"**Nombre total de pharmacies trouvées** : {len(st.session_state.pharmacies)}")
            st.markdown("<hr>", unsafe_allow_html=True)

            with st.expander("Pharmacies trouvées", expanded=False):
                st.markdown(
                    """
                    <style>
                    .pharmacy-list {
                        max-height: 300px;
                        overflow-y: auto;
                        padding: 10px;
                        border: 1px solid #ccc;
                        border-radius: 5px;
                        background-color: #f9f9f9;
                    }
                    </style>
                    """,
                    unsafe_allow_html=True
                )
                with st.container():
                    st.markdown('<div class="pharmacy-list">', unsafe_allow_html=True)
                    selected_pharmacies = []
                    for i, pharmacy in enumerate(st.session_state.pharmacies):
                        if st.checkbox(
                            pharmacy['name'],
                            key=f"pharmacy_{i}_{st.session_state.selected_pharmacies_key}",
                            value=pharmacy in st.session_state.selected_pharmacies
                        ):
                            selected_pharmacies.append(pharmacy)

                    if selected_pharmacies != st.session_state.selected_pharmacies:
                        st.session_state.selected_pharmacies = selected_pharmacies
                        st.session_state.selected_pharmacies_key = generate_pharmacies_key(selected_pharmacies)
                        st.session_state.map = _create_map(
                            st.session_state.pharmacies,
                            st.session_state.map_center['lat'],
                            st.session_state.map_center['lng'],
                            st.session_state.map_zoom,
                            selected_pharmacies=st.session_state.selected_pharmacies
                        )
                    st.markdown('</div>', unsafe_allow_html=True)

                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Tout cocher"):
                        st.session_state.selected_pharmacies = st.session_state.pharmacies
                        st.session_state.selected_pharmacies_key = generate_pharmacies_key(st.session_state.pharmacies)
                        st.session_state.map = _create_map(
                            st.session_state.pharmacies,
                            st.session_state.map_center['lat'],
                            st.session_state.map_center['lng'],
                            st.session_state.map_zoom,
                            selected_pharmacies=st.session_state.selected_pharmacies
                        )
                        logger.info(f"Tout cocher : {len(st.session_state.selected_pharmacies)} pharmacies sélectionnées")
                        st.rerun()
                with col2:
                    if st.button("Tout décocher"):
                        st.session_state.selected_pharmacies = []
                        st.session_state.selected_pharmacies_key = generate_pharmacies_key([])
                        st.session_state.map = _create_map(
                            st.session_state.pharmacies,
                            st.session_state.map_center['lat'],
                            st.session_state.map_center['lng'],
                            st.session_state.map_zoom,
                            selected_pharmacies=st.session_state.selected_pharmacies
                        )
                        logger.info("Tout décocher : aucune pharmacie sélectionnée")
                        st.rerun()

            st.markdown("<hr>", unsafe_allow_html=True)

            df_pharmacies = pd.DataFrame(st.session_state.pharmacies)
            csv_pharmacies = df_pharmacies.to_csv(index=False)
            st.download_button(
                label="Télécharger la liste des pharmacies (CSV)",
                data=csv_pharmacies,
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
            st.markdown("<hr>", unsafe_allow_html=True)

            if st.button("Nouvelle recherche"):
                app._reset_map_state()
                st.session_state.page = "Sélection de la zone"
                st.rerun()

        # Toujours afficher la carte, même vide
        center_lat = st.session_state.map_center['lat']
        center_lon = st.session_state.map_center['lng']
        if st.session_state.map is None or not st.session_state.get("selected_pharmacies_key"):
            if not st.session_state.get("selected_pharmacies"):
                st.session_state.selected_pharmacies = st.session_state.pharmacies
            st.session_state.selected_pharmacies_key = generate_pharmacies_key(st.session_state.selected_pharmacies or [])
            st.session_state.map = _create_map(
                st.session_state.pharmacies, center_lat, center_lon, st.session_state.map_zoom,
                selected_pharmacies=st.session_state.selected_pharmacies
            )
            logger.info(
                f"Carte régénérée : {len(st.session_state.pharmacies)} cercles, "
                f"selected={len(st.session_state.selected_pharmacies)}"
            )

        map_data = st_folium(st.session_state.map, width=MAP_WIDTH, height=MAP_HEIGHT, key="results_map")
        if map_data and isinstance(map_data, dict) and "center" in map_data and "zoom" in map_data and map_data["center"]:
            st.session_state.map_center = map_data["center"]
            st.session_state.map_zoom = map_data["zoom"]
            logger.info(f"Interaction avec la carte : map_center={st.session_state.map_center}, map_zoom={st.session_state.map_zoom}")


def render_billing_page(app):
    with st.container():
        st.header("Facturation")
        total_requests = app.storage_service.get_total_requests()
        st.write(f"Nombre total de requêtes effectuées (toutes sessions) : {total_requests}")
        st.write(f"Coût total estimé : {total_requests * 0.032:.2f}$")
        st.info("Ce coût est couvert par le crédit mensuel de 200$ de Google Maps Platform.")
        logger.info(f"Page Facturation : {total_requests} requêtes totales, coût estimé {total_requests * 0.032:.2f}$")


def render_history_page(app):
    with st.container():
        st.header("Historique des recherches")
        logger.info("Affichage de la page Historique des recherches")

        if st.session_state.is_admin:
            tab1, tab2 = st.tabs(["Mes recherches", "Recherches des utilisateurs"])

            with tab1:
                admin_history = [h for h in app.storage_service.load_search_history("admin")]
                _render_history_section(app, admin_history, user_id="admin")

            with tab2:
                other_history = [h for h in app.storage_service.load_search_history() if h.get("user_id") != "admin"]
                _render_history_section(app, other_history, user_id="*")

        else:
            user_id = st.session_state.username
            user_history = app.storage_service.load_search_history(user_id)

            if user_history:
                st.subheader(f"Historique pour {user_id}")
                _render_history_section(app, user_history, user_id=user_id)
            else:
                st.info("Aucun historique de recherche disponible pour cet utilisateur.")
                logger.info("Aucun historique de recherche à afficher")


def render_user_management_page(app):
    with st.container():
        st.header("Gestion des utilisateurs")
        logger.info("Affichage de la page Gestion des utilisateurs")

        st.subheader("Créer un nouvel utilisateur")
        new_username = st.text_input("Nom d'utilisateur", key="new_username")
        new_password = st.text_input("Mot de passe", type="password", key="new_password")
        initial_credits = st.number_input("Crédits initiaux", min_value=0, value=10, step=1)
        if st.button("Créer l'utilisateur"):
            if new_username and new_password:
                if app.user_service.create_user(new_username, new_password, initial_credits):
                    st.success(f"Utilisateur {new_username} créé avec {initial_credits} crédits.")
                else:
                    st.error(f"Erreur : l'utilisateur {new_username} existe déjà.")
            else:
                st.error("Erreur : veuillez entrer un nom d'utilisateur et un mot de passe.")
                logger.error("Tentative de création d'utilisateur avec des champs vides")

        st.subheader("Liste des utilisateurs")
        users = app.user_service.get_all_users()
        if not users:
            st.info("Aucun utilisateur enregistré.")
            logger.info("Aucun utilisateur dans la base")
        else:
            for username, user_data in users.items():
                if username != "admin":
                    st.write(f"Utilisateur : {username}, Crédits : {user_data['credits']}")
                    col1, col2 = st.columns(2)
                    with col1:
                        new_credits = st.number_input(
                            f"Modifier les crédits pour {username}",
                            min_value=0, value=user_data['credits'],
                            step=1, key=f"credits_{username}"
                        )
                        if st.button(f"Mettre à jour les crédits", key=f"update_{username}"):
                            if app.user_service.update_credits(username, new_credits):
                                st.success(f"Crédits mis à jour pour {username} : {new_credits} crédits.")
                    with col2:
                        if st.button(f"Supprimer {username}", key=f"delete_{username}"):
                            if app.user_service.delete_user(username):
                                st.success(f"Utilisateur {username} supprimé.")
                                st.rerun()


def _render_history_section(app, history, user_id):
    if not history:
        st.info("Aucun historique de recherche disponible.")
        return

    for idx, search in enumerate(history):
        pharmacies = app.storage_service.get_pharmacies_from_subzones(search.get("subzones_used", []))

        with st.expander(f"Recherche : {search['name']} (Type : {search['search_type']})"):
            st.write(f"Date : {search.get('timestamp', 'Inconnue')}")
            st.write(f"Nombre de pharmacies : {len(pharmacies)}")
            # (Plus d'affichage des requêtes API ici)

            if 'map_html' in search and search['map_html']:
                st.components.v1.html(search['map_html'], width=MINI_MAP_WIDTH, height=MINI_MAP_HEIGHT)
            else:
                st.warning("Carte non disponible pour cette recherche.")

            col1, col2, col3 = st.columns([1, 1, 1])

            with col1:
                if st.button("Visualiser", key=f"view_{search['name']}_{idx}"):
                    logger.info(f"Visualisation de l'historique {search['name']}")
                    st.session_state.bounds = tuple(search["bounds"])
                    st.session_state.search_type = search["search_type"]
                    st.session_state.subarea_step = search.get("subarea_step")
                    st.session_state.subarea_radius = search.get("subarea_radius")
                    st.session_state.total_requests = search.get("total_requests", 0)
                    st.session_state.search_name = search["name"]
                    st.session_state.zone_validated = True

                    # Center/zoom d'abord
                    st.session_state.map_center = {'lat': search["center_lat"], 'lng': search["center_lon"]}
                    st.session_state.map_zoom = search["zoom"]

                    # 1) Essayer depuis l'historique
                    subzones_used = search.get("subzones_used", []) or []
                    st.session_state.last_subzones_used = subzones_used
                    pharmacies = app.storage_service.get_pharmacies_from_subzones(subzones_used)

                    # 2) Si vide, reconstruire la GRILLE à partir des bounds (filet de sécurité pour anciens enregistrements)
                    if not pharmacies:
                        lat_min, lat_max, lon_min, lon_max = st.session_state.bounds
                        step = st.session_state.subarea_step or 0.01
                        radius = st.session_state.subarea_radius or 1000
                        grid_subzones = [
                            generate_subzone_key(sz_lat, sz_lon, radius)
                            for sz_lat in np.arange(lat_min, lat_max, step)
                            for sz_lon in np.arange(lon_min, lon_max, step)
                        ]
                        st.session_state.last_subzones_used = list(dict.fromkeys(grid_subzones))
                        pharmacies = app.storage_service.get_pharmacies_from_subzones(st.session_state.last_subzones_used)

                    st.session_state.pharmacies = pharmacies
                    st.session_state.selected_pharmacies = pharmacies
                    st.session_state.selected_pharmacies_key = generate_pharmacies_key(pharmacies)

                    st.session_state.map = _create_map(
                        pharmacies,
                        st.session_state.map_center['lat'],
                        st.session_state.map_center['lng'],
                        st.session_state.map_zoom,
                        selected_pharmacies=pharmacies
                    )
                    st.session_state.page = "Résultats"
                    st.rerun()

            with col2:
                df = pd.DataFrame(pharmacies)
                csv = df.to_csv(index=False)
                st.download_button(
                    label="Télécharger CSV",
                    data=csv,
                    file_name=f"pharmacies_{search['name']}.csv",
                    mime="text/csv",
                    key=f"csv_{search['name']}_{idx}"
                )

            with col3:
                if st.button("Supprimer", key=f"delete_{search['name']}_{idx}"):
                    full = app.storage_service.load_search_history()
                    updated = [h for h in full if h['name'] != search['name'] or h['user_id'] != search.get("user_id")]
                    app.storage_service.save_search_history(updated, overwrite=True)
                    st.success("Recherche supprimée.")
                    st.rerun()
