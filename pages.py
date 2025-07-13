import streamlit as st
import folium
import pandas as pd
from streamlit_folium import st_folium
import numpy as np
from itertools import product
from datetime import datetime
import logging
from utils.helpers import estimate_bounds, generate_pharmacies_key

logger = logging.getLogger(__name__)

# Constantes
DEFAULT_CENTER = {'lat': 33.5731, 'lng': -7.5898}  # Casablanca
DEFAULT_ZOOM = 12
CIRCLE_RADIUS = 300  # 30000 cm = 300 mètres
CIRCLE_OPACITY = 0.5
MAP_WIDTH = "100%"
MAP_HEIGHT = 600
MINI_MAP_WIDTH = 300
MINI_MAP_HEIGHT = 200
MAX_AREA_KM2 = 4.0

def _create_map(pharmacies, center_lat, center_lon, zoom, width=MAP_WIDTH, height=MAP_HEIGHT, area_too_large=False, bounds=None, selected_pharmacies=None):
    """Créer une carte Folium avec des cercles pour les pharmacies."""
    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom, width=width, height=height)
    selected_pharmacies = selected_pharmacies or []
    for pharmacy in pharmacies:
        is_selected = any(p['name'] == pharmacy['name'] and p['latitude'] == pharmacy['latitude'] and p['longitude'] == pharmacy['longitude'] for p in selected_pharmacies)
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
    if area_too_large and bounds:
        lat_min, lat_max, lon_min, lon_max = bounds
        folium.Rectangle(
            bounds=[[lat_min, lon_min], [lat_max, lon_max]],
            color='red',
            fill=True,
            fill_color='red',
            fill_opacity=0.2,
            opacity=0.3,
            popup="Zone trop grande"
        ).add_to(m)
    logger.info(f"Carte créée : {len(pharmacies)} cercles, center=({center_lat:.4f}, {center_lon:.4f}), zoom={zoom}, area_too_large={area_too_large}")
    return m

def _calculate_area_km2(lat_min, lat_max, lon_min, lon_max):
    """Calculer la superficie de la zone en km²."""
    lat_km = (lat_max - lat_min) * 111
    lon_km = (lon_max - lon_min) * 111 * np.cos(np.radians((lat_min + lat_max) / 2))
    area = lat_km * lon_km
    return area

def _find_non_covered_points(pharmacies, lat_min, lat_max, lon_min, lon_max):
    """Identifier les points non couverts par un cercle de 300m."""
    grid_step = 0.0027  # ≈ 300m
    lat_points = np.arange(lat_min, lat_max, grid_step)
    lon_points = np.arange(lon_min, lon_max, grid_step)
    non_covered_points = []
    for lat, lon in product(lat_points, lon_points):
        is_covered = False
        for pharmacy in pharmacies:
            distance = np.sqrt(
                ((lat - pharmacy['latitude']) * 111 * 1000) ** 2 +
                ((lon - pharmacy['longitude']) * 111 * np.cos(np.radians(lat)) * 1000) ** 2
            )
            if distance <= CIRCLE_RADIUS:
                is_covered = True
                break
        if not is_covered:
            non_covered_points.append({'latitude': lat, 'longitude': lon})
    logger.info(f"{len(non_covered_points)} points non couverts trouvés")
    return non_covered_points

def _process_search(app, lat_min, lat_max, lon_min, lon_max, subarea_step, subarea_radius, search_name, user_id):
    """Traiter la recherche de pharmacies et zones non couvertes."""
    logger.info(f"Lancement de la recherche : name={search_name}, user_id={user_id}, step={subarea_step}, radius={subarea_radius}")
    try:
        st.session_state.search_name = search_name
        st.session_state.search_type = "quick" if subarea_radius == 1000 else "advanced"
        st.session_state.subarea_step = subarea_step
        st.session_state.subarea_radius = subarea_radius
        st.session_state.search_in_progress = True
        st.write("Recherche en cours...")

        pharmacies, total_requests = app.pharmacy_service.get_pharmacies_in_area(
            lat_min, lat_max, lon_min, lon_max, subarea_step, subarea_radius
        )
        if not pharmacies:
            st.error("Aucune pharmacie trouvée. Vérifiez votre clé API ou la zone.")
            logger.error("Aucune pharmacie trouvée")
            st.write("Vérifiez sur https://www.google.com/maps en recherchant 'pharmacy'.")
            _reset_search()
        else:
            non_covered_points = _find_non_covered_points(pharmacies, lat_min, lat_max, lon_min, lon_max)
            st.session_state.pharmacies = pharmacies
            st.session_state.non_covered_points = non_covered_points
            st.session_state.total_requests = total_requests
            center_lat = (lat_min + lat_max) / 2
            center_lon = (lon_min + lon_max) / 2
            st.session_state.map = _create_map(pharmacies, center_lat, center_lon,
                                              st.session_state.map_zoom)
            st.session_state.map_center = {'lat': center_lat, 'lng': center_lon}
            st.session_state.selected_pharmacies = []
            st.session_state.selected_pharmacies_key = generate_pharmacies_key([])
            search_data = {
                "name": search_name,
                "user_id": user_id,
                "bounds": st.session_state.bounds,
                "search_type": st.session_state.search_type,
                "subarea_step": subarea_step,
                "subarea_radius": subarea_radius,
                "pharmacies": pharmacies,
                "non_covered_points": non_covered_points,
                "total_requests": total_requests,
                "map_html": st.session_state.map._repr_html_(),
                "center_lat": center_lat,
                "center_lon": center_lon,
                "zoom": st.session_state.map_zoom,
                "timestamp": datetime.utcnow().isoformat()
            }
            app.storage_service.save_search_history(search_data)
            app.storage_service.increment_total_requests(user_id, total_requests)
            if not st.session_state.is_admin:
                st.session_state.search_history = app.storage_service.load_search_history(user_id)
            else:
                st.session_state.search_history = app.storage_service.load_search_history()
            st.session_state.search_in_progress = False
            st.session_state.page = "Résultats"
            logger.info(f"Recherche terminée : {len(pharmacies)} pharmacies trouvées, "
                        f"{len(non_covered_points)} points non couverts, {total_requests} requêtes")
    except Exception as e:
        st.error(f"Erreur lors du lancement de la recherche : {e}")
        logger.error(f"Erreur lors du lancement de la recherche : {e}")
        _reset_search()

def _reset_search():
    """Réinitialiser l'état après une recherche échouée."""
    st.session_state.search_in_progress = False
    st.session_state.page = "Sélection de la zone"
    st.session_state.map = None
    st.session_state.selected_pharmacies_key = None
    st.session_state.area_too_large = False
    st.session_state.selected_pharmacies = []
    logger.info("État réinitialisé : search_in_progress=False, map=None, selected_pharmacies_key=None")

def render_login_page(app):
    """Afficher la page de connexion."""
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
                    st.success("Connexion administrateur réussie !")
                    logger.info("Connexion administrateur réussie")
                    st.rerun()
                else:
                    st.error("Mot de passe administrateur incorrect.")
                    logger.warning("Échec de la connexion administrateur")

def render_selection_page(app):
    """Afficher la page de sélection de la zone de recherche."""
    with st.container():
        st.header("Sélection de la zone de recherche")
        if not st.session_state.is_admin:
            credits = app.user_service.get_user_credits(st.session_state.username)
            st.write(f"Crédits disponibles : {credits}")
        st.write("Ajustez la carte pour définir une zone de recherche (max 4 km² pour les utilisateurs non-admin).")

        m = folium.Map(location=[DEFAULT_CENTER['lat'], DEFAULT_CENTER['lng']], zoom_start=DEFAULT_ZOOM)
        area_too_large = st.session_state.get('area_too_large', False)
        if st.session_state.bounds and not st.session_state.is_admin:
            lat_min, lat_max, lon_min, lon_max = st.session_state.bounds
            area_km2 = _calculate_area_km2(lat_min, lat_max, lon_min, lon_max)
            area_too_large = area_km2 > MAX_AREA_KM2
            if area_too_large:
                m = _create_map([], center_lat=DEFAULT_CENTER['lat'], center_lon=DEFAULT_CENTER['lng'], zoom=DEFAULT_ZOOM, area_too_large=True, bounds=st.session_state.bounds)
        map_data = st_folium(m, width=MAP_WIDTH, height=MAP_HEIGHT, key="selection_map")
        logger.info(f"Données de la carte : {map_data}")

        search_name = st.text_input("Nom de la recherche", placeholder="Entrez un nom unique pour la recherche")

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
                        area_km2 = _calculate_area_km2(lat_min, lat_max, lon_min, lon_max)
                        st.session_state.bounds = (lat_min, lat_max, lon_min, lon_max)
                        st.session_state.area_too_large = not st.session_state.is_admin and area_km2 > MAX_AREA_KM2
                        if not st.session_state.is_admin and area_km2 > MAX_AREA_KM2:
                            st.error(f"Erreur : la zone est trop grande ({area_km2:.2f} km²). Limitez à {MAX_AREA_KM2} km².")
                            logger.error(f"Zone trop grande : {area_km2:.2f} km²")
                        else:
                            st.write(f"Zone validée : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, "
                                     f"lon_min={lon_min:.4f}, lon_max={lon_max:.4f} ({area_km2:.2f} km²)")
                            logger.info(f"Zone validée : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, "
                                        f"lon_min={lon_min:.4f}, lon_max={lon_max:.4f}, area={area_km2:.2f} km²")
                        st.session_state.search_in_progress = False
                    else:
                        st.error("Erreur : les coordonnées de la zone sont invalides.")
                        logger.error("Coordonnées de la zone invalides")
                except (KeyError, TypeError) as e:
                    logger.warning(f"Erreur lors de la récupération des limites : {e}")
                    center = map_data.get("center", DEFAULT_CENTER)
                    zoom = map_data.get("zoom", DEFAULT_ZOOM)
                    lat_min, lat_max, lon_min, lon_max = estimate_bounds(center["lat"], center["lng"], zoom)
                    area_km2 = _calculate_area_km2(lat_min, lat_max, lon_min, lon_max)
                    if not st.session_state.is_admin and area_km2 > MAX_AREA_KM2:
                        st.session_state.area_too_large = True
                        st.error(f"Erreur : la zone estimée est trop grande ({area_km2:.2f} km²). Limitez à {MAX_AREA_KM2} km².")
                        logger.error(f"Zone estimée trop grande : {area_km2:.2f} km²")
                    else:
                        st.session_state.area_too_large = False
                        st.session_state.bounds = (lat_min, lat_max, lon_min, lon_max)
                        st.write(f"Zone validée (estimée) : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, "
                                 f"lon_min={lon_min:.4f}, lon_max={lon_max:.4f} ({area_km2:.2f} km²)")
                        logger.info(f"Zone validée (estimée) : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, "
                                    f"lon_min={lon_min:.4f}, lon_max={lon_max:.4f}")
            else:
                st.error("Erreur : impossible de récupérer la zone visible. Ajustez la carte et réessayez.")
                logger.error("Impossible de récupérer la zone visible")
                st.session_state.area_too_large = False

        if st.session_state.bounds and not st.session_state.area_too_large:
            lat_min, lat_max, lon_min, lon_max = st.session_state.bounds
            if lat_min < lat_max and lon_min < lon_max:
                st.subheader("Type de recherche")
                search_type = st.radio("Choisir le type de recherche",
                                       ["Recherche rapide (moins de requêtes)", "Recherche avancée (grille fine)"],
                                       index=0)
                subarea_step = 0.01 if "rapide" in search_type.lower() else 0.005
                subarea_radius = 1000 if "rapide" in search_type.lower() else 500
                estimated_subareas = len(list(product(
                    np.arange(lat_min, lat_max, subarea_step),
                    np.arange(lon_min, lon_max, subarea_step)
                )))
                st.warning(f"Cette recherche peut générer ~{estimated_subareas} requêtes, "
                           f"coût estimé : {estimated_subareas * 0.032:.2f}$")
                logger.info(f"Estimation : {estimated_subareas} sous-zones, coût ~{estimated_subareas * 0.032:.2f}$")
                if st.button("Lancer la recherche", disabled=not search_name or not app.storage_service.is_search_name_unique(search_name, st.session_state.username)):
                    if not st.session_state.is_admin and app.user_service.get_user_credits(st.session_state.username) < estimated_subareas:
                        st.error("Erreur : crédits insuffisants pour cette recherche.")
                        logger.error(f"Crédits insuffisants pour {st.session_state.username}")
                    else:
                        _process_search(app, lat_min, lat_max, lon_min, lon_max, subarea_step, subarea_radius, search_name, st.session_state.username)
        elif st.session_state.area_too_large:
            st.error("Veuillez réduire la zone de recherche avant de continuer.")
            logger.error("Recherche bloquée : zone trop grande")
        st.rerun()

def render_results_page(app):
    """Afficher la page des résultats."""
    with st.container():
        st.header("Résultats de la recherche")
        logger.info("Affichage de la page Résultats")

        required_keys = ["bounds", "search_type", "pharmacies", "total_requests", "search_name"]
        if not all(key in st.session_state and st.session_state[key] is not None for key in required_keys):
            st.error("Aucune recherche récente disponible. Retournez à la page de sélection pour lancer une recherche.")
            logger.error("Données de recherche manquantes pour afficher les résultats")
            st.session_state.page = "Sélection de la zone"
            st.rerun()
            return

        lat_min, lat_max, lon_min, lon_max = st.session_state.bounds
        search_name = st.session_state.search_name
        logger.info(f"Paramètres : name={search_name}, lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, "
                    f"lon_min={lon_min:.4f}, lon_max={lon_max:.4f}, "
                    f"step={st.session_state.subarea_step}, radius={st.session_state.subarea_radius}")

        st.write(f"Nom de la recherche : {search_name}")
        st.write(f"Nombre total de pharmacies trouvées : {len(st.session_state.pharmacies)}")
        if st.session_state.is_admin:
            st.write(f"Nombre total de points non couverts : {len(st.session_state.non_covered_points)}")
            st.write(f"Nombre total de requêtes effectuées : {st.session_state.total_requests}")

        with st.container():
            if st.session_state.map is None:
                center_lat = st.session_state.map_center['lat']
                center_lon = st.session_state.map_center['lng']
                selected_pharmacies = st.session_state.get("selected_pharmacies", [])
                st.session_state.map = _create_map(st.session_state.pharmacies, center_lat, center_lon,
                                                  st.session_state.map_zoom, selected_pharmacies=selected_pharmacies)
                st.session_state.selected_pharmacies_key = generate_pharmacies_key(selected_pharmacies)
                logger.info(f"Carte régénérée : {len(st.session_state.pharmacies)} cercles, "
                            f"selected={len(selected_pharmacies)}")

            if st.session_state.selected_pharmacies_key:
                map_data = st_folium(st.session_state.map, width=MAP_WIDTH, height=MAP_HEIGHT,
                                     key=f"results_map_{st.session_state.selected_pharmacies_key}")
                if map_data and "center" in map_data and "zoom" in map_data and map_data["center"] and map_data["zoom"]:
                    st.session_state.map_center = map_data["center"]
                    st.session_state.map_zoom = map_data["zoom"]
                    logger.info(f"Interaction avec la carte : map_center={st.session_state.map_center}, "
                                f"map_zoom={st.session_state.map_zoom}")

        with st.expander("Pharmacies trouvées", expanded=True):
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
                for i, pharmacy in enumerate(st.session_state.pharmacies):
                    if st.checkbox(pharmacy['name'], key=f"pharmacy_{i}", value=False):
                        selected_pharmacies.append(pharmacy)
                st.markdown('</div>', unsafe_allow_html=True)

        if st.button("Recalculer"):
            st.session_state.selected_pharmacies = selected_pharmacies
            non_covered_points = _find_non_covered_points(selected_pharmacies, lat_min, lat_max, lon_min, lon_max)
            st.session_state.non_covered_points = non_covered_points
            st.session_state.selected_pharmacies_key = generate_pharmacies_key(selected_pharmacies)
            center_lat = st.session_state.map_center['lat']
            center_lon = st.session_state.map_center['lng']
            st.session_state.map = _create_map(st.session_state.pharmacies, center_lat, center_lon,
                                              st.session_state.map_zoom, selected_pharmacies=selected_pharmacies)
            logger.info(f"Carte mise à jour après recalcul : {len(st.session_state.pharmacies)} cercles, "
                        f"selected={len(selected_pharmacies)}")

        df_pharmacies = pd.DataFrame(st.session_state.pharmacies)
        csv_pharmacies = df_pharmacies.to_csv(index=False)
        st.download_button(
            label="Télécharger la liste des pharmacies (CSV)",
            data=csv_pharmacies,
            file_name=f"pharmacies_{search_name}.csv",
            mime="text/csv"
        )
        if st.session_state.is_admin:
            df_non_covered = pd.DataFrame(st.session_state.non_covered_points)
            if not df_non_covered.empty:
                csv_non_covered = df_non_covered.to_csv(index=False)
                st.download_button(
                    label="Télécharger les zones non couvertes (CSV)",
                    data=csv_non_covered,
                    file_name=f"non_covered_zones_{search_name}.csv",
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

        if st.button("Nouvelle recherche"):
            st.session_state.page = "Sélection de la zone"
            st.rerun()

def render_billing_page(app):
    """Afficher la page de facturation."""
    with st.container():
        st.header("Facturation")
        total_requests = app.storage_service.get_total_requests()
        st.write(f"Nombre total de requêtes effectuées (toutes sessions) : {total_requests}")
        st.write(f"Coût total estimé : {total_requests * 0.032:.2f}$")
        st.info("Ce coût est couvert par le crédit mensuel de 200$ de Google Maps Platform.")
        logger.info(f"Page Facturation : {total_requests} requêtes totales, coût estimé {total_requests * 0.032:.2f}$")

def render_history_page(app):
    """Afficher la page de l'historique des recherches."""
    with st.container():
        st.header("Historique des recherches")
        logger.info("Affichage de la page Historique des recherches")

        user_id = st.session_state.username
        search_history = app.storage_service.load_search_history(user_id)
        st.session_state.search_history = search_history

        if not search_history:
            st.info("Aucun historique de recherche disponible pour cet utilisateur.")
            logger.info(f"Aucun historique de recherche pour {user_id}")
            return

        st.subheader(f"Historique pour {user_id}")
        for search in search_history:
            with st.expander(f"Recherche : {search['name']} (Type : {search['search_type']})"):
                st.write(f"Date : {search.get('timestamp', 'Inconnue')}")
                st.write(f"Nombre de pharmacies : {len(search['pharmacies'])}")
                if st.session_state.is_admin:
                    st.write(f"Requêtes API : {search['total_requests']}")
                mini_map = _create_map(
                    search["pharmacies"],
                    search["center_lat"],
                    search["center_lon"],
                    search["zoom"],
                    width=MINI_MAP_WIDTH,
                    height=MINI_MAP_HEIGHT
                )
                st_folium(mini_map, width=MINI_MAP_WIDTH, height=MINI_MAP_HEIGHT,
                          key=f"mini_map_{search['name']}")

                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("Visualiser", key=f"view_{search['name']}"):
                        st.session_state.bounds = search["bounds"]
                        st.session_state.search_type = search["search_type"]
                        st.session_state.subarea_step = search["subarea_step"]
                        st.session_state.subarea_radius = search["subarea_radius"]
                        st.session_state.pharmacies = search["pharmacies"]
                        st.session_state.non_covered_points = search.get("non_covered_points", [])
                        st.session_state.total_requests = search["total_requests"]
                        st.session_state.search_name = search["name"]
                        st.session_state.map = _create_map(
                            search["pharmacies"],
                            search["center_lat"],
                            search["center_lon"],
                            search["zoom"],
                            selected_pharmacies=[]
                        )
                        st.session_state.map_center = {'lat': search["center_lat"], 'lng': search["center_lon"]}
                        st.session_state.map_zoom = search["zoom"]
                        st.session_state.selected_pharmacies = []
                        st.session_state.selected_pharmacies_key = generate_pharmacies_key([])
                        st.session_state.page = "Résultats"
                        logger.info(f"Visualisation de la recherche '{search['name']}': passage à la page Résultats")
                        st.rerun()
                with col2:
                    df = pd.DataFrame(search["pharmacies"])
                    csv = df.to_csv(index=False)
                    st.download_button(
                        label="Télécharger CSV Pharmacies",
                        data=csv,
                        file_name=f"pharmacies_{search['name']}.csv",
                        mime="text/csv",
                        key=f"csv_pharmacies_{search['name']}"
                    )
                with col3:
                    if st.session_state.is_admin:
                        df_non_covered = pd.DataFrame(search.get("non_covered_points", []))
                        if not df_non_covered.empty:
                            csv_non_covered = df_non_covered.to_csv(index=False)
                            st.download_button(
                                label="Télécharger CSV Zones non couvertes",
                                data=csv_non_covered,
                                file_name=f"non_covered_zones_{search['name']}.csv",
                                mime="text/csv",
                                key=f"csv_non_covered_{search['name']}"
                            )

def render_user_management_page(app):
    """Afficher la page de gestion des utilisateurs."""
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
                        new_credits = st.number_input(f"Modifier les crédits pour {username}",
                                                      min_value=0, value=user_data['credits'],
                                                      step=1, key=f"credits_{username}")
                        if st.button(f"Mettre à jour les crédits", key=f"update_{username}"):
                            if app.user_service.update_credits(username, new_credits):
                                st.success(f"Crédits mis à jour pour {username} : {new_credits} crédits.")
                    with col2:
                        if st.button(f"Supprimer {username}", key=f"delete_{username}"):
                            if app.user_service.delete_user(username):
                                st.success(f"Utilisateur {username} supprimé.")
                                st.rerun()