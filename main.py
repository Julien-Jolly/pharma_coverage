import streamlit as st
import folium
import pandas as pd
from streamlit_folium import st_folium
import numpy as np
import logging
from itertools import product
import numpy as np
from services.pharmacy_service import PharmacyService
from services.storage_service import StorageService
from services.user_services import UserService
from utils.helpers import estimate_bounds, generate_pharmacies_key
from itertools import product

# Configurer les journaux
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constantes
DEFAULT_CENTER = {'lat': 33.5731, 'lng': -7.5898}  # Casablanca
DEFAULT_ZOOM = 12
CIRCLE_RADIUS = 300  # mètres
CIRCLE_OPACITY = 0.5
MAP_WIDTH = 700
MAP_HEIGHT = 500
MINI_MAP_WIDTH = 300
MINI_MAP_HEIGHT = 200
MAX_AREA_KM2 = 4.0  # Limite de la zone de recherche
NON_COVERED_RADIUS = 100  # Rayon des cercles pour les zones non couvertes


class PharmacyApp:
    """Application Streamlit pour la recherche de pharmacies et gestion des utilisateurs."""

    def __init__(self):
        """Initialiser l'application et les services."""
        self.storage_service = StorageService()
        self.user_service = UserService(self.storage_service)
        self.pharmacy_service = PharmacyService()
        self._initialize_session_state()
        logger.info(f"Initialisation : page={st.session_state.page}, "
                    f"search_in_progress={st.session_state.search_in_progress}, "
                    f"map={'défini' if st.session_state.map else 'non défini'}, "
                    f"map_center={st.session_state.map_center}, "
                    f"map_zoom={st.session_state.map_zoom}, "
                    f"search_history={len(st.session_state.search_history)} recherches, "
                    f"is_admin={st.session_state.is_admin}, "
                    f"username={st.session_state.username}")

    def _initialize_session_state(self):
        """Initialiser les variables de session."""
        defaults = {
            'page': "Connexion",
            'search_in_progress': False,
            'map': None,
            'map_center': DEFAULT_CENTER,
            'map_zoom': DEFAULT_ZOOM,
            'search_history': [],
            'selected_pharmacies_key': None,
            'show_non_covered': False,
            'is_authenticated': False,
            'is_admin': False,
            'username': None,
            'bounds': None,
            'search_type': None,
            'search_name': None,
            'pharmacies': [],
            'non_covered_points': [],
            'total_requests': 0,
            'selected_pharmacies': [],
            'subarea_step': None,
            'subarea_radius': None
        }
        for key, value in defaults.items():
            if key not in st.session_state:
                st.session_state[key] = value

    def _create_map(self, pharmacies, non_covered_points, center_lat, center_lon, zoom, width=MAP_WIDTH,
                    height=MAP_HEIGHT):
        """Créer une carte Folium avec des cercles de 300m pour les pharmacies et des cercles pour les zones non couvertes."""
        m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom, width=width, height=height)
        for pharmacy in pharmacies:
            folium.Circle(
                location=[pharmacy['latitude'], pharmacy['longitude']],
                radius=CIRCLE_RADIUS,
                color='green',
                fill=True,
                fill_color='green',
                fill_opacity=CIRCLE_OPACITY,
                opacity=CIRCLE_OPACITY,
                popup=pharmacy['name']
            ).add_to(m)
        if st.session_state.show_non_covered:
            for point in non_covered_points:
                folium.Circle(
                    location=[point['latitude'], point['longitude']],
                    radius=NON_COVERED_RADIUS,
                    color='red',
                    fill=True,
                    fill_color='red',
                    fill_opacity=0.3,
                    opacity=0.3,
                    popup="Zone non couverte"
                ).add_to(m)
        logger.info(f"Carte créée : {len(pharmacies)} cercles de pharmacies, "
                    f"{len(non_covered_points)} points non couverts, "
                    f"center=({center_lat:.4f}, {center_lon:.4f}), zoom={zoom}, "
                    f"width={width}, height={height}")
        return m

    def _calculate_area_km2(self, lat_min, lat_max, lon_min, lon_max):
        """Calculer la superficie de la zone en km²."""
        lat_km = (lat_max - lat_min) * 111
        lon_km = (lon_max - lon_min) * 111 * np.cos(np.radians((lat_min + lat_max) / 2))
        area = lat_km * lon_km
        return area

    def _find_non_covered_points(self, pharmacies, lat_min, lat_max, lon_min, lon_max):
        """Identifier les points non couverts par un cercle de 300m."""
        grid_step = 0.0009  # ≈ 100m
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

    def _render_login_page(self):
        """Afficher la page de connexion."""
        st.header("Connexion")
        login_type = st.radio("Type de connexion", ["Utilisateur", "Administrateur"], index=0)

        if login_type == "Utilisateur":
            username = st.text_input("Nom d'utilisateur")
            password = st.text_input("Mot de passe", type="password")
            if st.button("Se connecter"):
                if self.user_service.authenticate_user(username, password):
                    credits = self.user_service.get_user_credits(username)
                    if credits is not None:
                        st.session_state.is_authenticated = True
                        st.session_state.is_admin = False
                        st.session_state.username = username
                        st.session_state.search_history = self.storage_service.load_search_history(username)
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
                if self.user_service.authenticate_admin(password):
                    st.session_state.is_authenticated = True
                    st.session_state.is_admin = True
                    st.session_state.username = "admin"
                    st.session_state.search_history = self.storage_service.load_search_history()
                    st.session_state.page = "Sélection de la zone"
                    st.success("Connexion administrateur réussie !")
                    logger.info("Connexion administrateur réussie")
                    st.rerun()
                else:
                    st.error("Mot de passe administrateur incorrect.")
                    logger.warning("Échec de la connexion administrateur")

    def _render_selection_page(self):
        """Afficher la page de sélection de la zone de recherche."""
        st.header("Sélection de la zone de recherche")
        if not st.session_state.is_admin:
            credits = self.user_service.get_user_credits(st.session_state.username)
            st.write(f"Crédits disponibles : {credits}")
        st.write("Ajustez la carte pour définir une zone de recherche (max 4 km²).")

        m = folium.Map(location=[DEFAULT_CENTER['lat'], DEFAULT_CENTER['lng']], zoom_start=DEFAULT_ZOOM)
        map_data = st_folium(m, width=MAP_WIDTH, height=MAP_HEIGHT)
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
                        area_km2 = self._calculate_area_km2(lat_min, lat_max, lon_min, lon_max)
                        if area_km2 > MAX_AREA_KM2:
                            st.error(
                                f"Erreur : la zone est trop grande ({area_km2:.2f} km²). Limitez à {MAX_AREA_KM2} km².")
                            logger.error(f"Zone trop grande : {area_km2:.2f} km²")
                            center_lat = (lat_min + lat_max) / 2
                            center_lon = (lon_min + lon_max) / 2
                            delta = np.sqrt(MAX_AREA_KM2 / (111 * 111 * np.cos(np.radians(center_lat))))
                            lat_min = center_lat - delta / 2
                            lat_max = center_lat + delta / 2
                            lon_min = center_lon - delta / (2 * np.cos(np.radians(center_lat)))
                            lon_max = center_lon + delta / (2 * np.cos(np.radians(center_lat)))
                            st.warning(f"Zone ajustée à : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, "
                                       f"lon_min={lon_min:.4f}, lon_max={lon_max:.4f}")
                            logger.info(f"Zone ajustée : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, "
                                        f"lon_min={lon_min:.4f}, lon_max={lon_max:.4f}")
                        st.session_state.bounds = (lat_min, lat_max, lon_min, lon_max)
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
                    area_km2 = self._calculate_area_km2(lat_min, lat_max, lon_min, lon_max)
                    if area_km2 > MAX_AREA_KM2:
                        center_lat = center["lat"]
                        center_lon = center["lng"]
                        delta = np.sqrt(MAX_AREA_KM2 / (111 * 111 * np.cos(np.radians(center_lat))))
                        lat_min = center_lat - delta / 2
                        lat_max = center_lat + delta / 2
                        lon_min = center_lon - delta / (2 * np.cos(np.radians(center_lat)))
                        lon_max = center_lon + delta / (2 * np.cos(np.radians(center_lat)))
                        st.warning(f"Zone estimée ajustée à : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, "
                                   f"lon_min={lon_min:.4f}, lon_max={lon_max:.4f}")
                        logger.info(f"Zone estimée ajustée : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, "
                                    f"lon_min={lon_min:.4f}, lon_max={lon_max:.4f}")
                    if lat_min < lat_max and lon_min < lon_max:
                        st.session_state.bounds = (lat_min, lat_max, lon_min, lon_max)
                        st.write(f"Zone validée (estimée) : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, "
                                 f"lon_min={lon_min:.4f}, lon_max={lon_max:.4f}")
                        logger.info(f"Zone validée (estimée) : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, "
                                    f"lon_min={lon_min:.4f}, lon_max={lon_max:.4f}")
                    else:
                        st.error("Erreur : les coordonnées estimées de la zone sont invalides.")
                        logger.error("Coordonnées estimées de la zone invalides")
            else:
                st.error("Erreur : impossible de récupérer la zone visible. Ajustez la carte et réessayez.")
                logger.error("Impossible de récupérer la zone visible")

        if "bounds" in st.session_state:
            lat_min, lat_max, lon_min, lon_max = st.session_state.bounds
            if lat_min < lat_max and lon_min < lon_max:
                st.subheader("Type de recherche")
                search_type = st.radio("Choisir le type de recherche",
                                       ["Recherche rapide (moins de requêtes)", "Recherche avancée (grille fine)"],
                                       index=0)
                subarea_step = 5 if "rapide" in search_type.lower() else 10  # Nombre de sous-zones
                subarea_radius = 1000 if "rapide" in search_type.lower() else 500  # Rayon en mètres

                estimated_subareas = subarea_step * subarea_step
                st.warning(f"Cette recherche peut générer ~{estimated_subareas} requêtes, "
                           f"coût estimé : {estimated_subareas * 0.032:.2f}$")
                logger.info(f"Estimation : {estimated_subareas} sous-zones, coût ~{estimated_subareas * 0.032:.2f}$")

                if st.button("Lancer la recherche"):
                    if not search_name:
                        st.error("Erreur : veuillez entrer un nom pour la recherche.")
                        logger.error("Nom de recherche vide")
                    elif not self.storage_service.is_search_name_unique(search_name, st.session_state.username):
                        st.error(f"Erreur : le nom '{search_name}' est déjà utilisé.")
                        logger.error(
                            f"Nom de recherche '{search_name}' déjà utilisé pour l'utilisateur {st.session_state.username}")
                    elif not st.session_state.is_admin and self.user_service.get_user_credits(
                            st.session_state.username) < 1:
                        st.error("Erreur : crédits insuffisants pour lancer une recherche.")
                        logger.error(f"Crédits insuffisants pour {st.session_state.username}")
                    else:
                        if not st.session_state.is_admin:
                            credits = self.user_service.get_user_credits(st.session_state.username)
                            self.user_service.update_credits(st.session_state.username, credits - 1)
                        self._process_search(lat_min, lat_max, lon_min, lon_max,
                                             subarea_step, subarea_radius, search_name, st.session_state.username)

    def _process_search(self, lat_min, lat_max, lon_min, lon_max, subarea_step, subarea_radius, search_name, user_id):
        """Traiter la recherche de pharmacies et zones non couvertes."""
        logger.info(
            f"Lancement de la recherche : name={search_name}, user_id={user_id}, step={subarea_step}, radius={subarea_radius}")
        try:
            st.session_state.search_name = search_name
            st.session_state.search_type = "quick" if subarea_radius == 1000 else "advanced"
            st.session_state.subarea_step = subarea_step
            st.session_state.subarea_radius = subarea_radius
            st.session_state.search_in_progress = True
            st.write("Recherche en cours...")

            pharmacies, total_requests = self.pharmacy_service.get_pharmacies_in_area(
                lat_min, lat_max, lon_min, lon_max, subarea_step, subarea_radius
            )
            if not pharmacies:
                st.error("Aucune pharmacie trouvée. Vérifiez votre clé API ou la zone.")
                logger.error("Aucune pharmacie trouvée")
                st.write("Vérifiez sur https://www.google.com/maps en recherchant 'pharmacy'.")
                self._reset_search()
            else:
                non_covered_points = self._find_non_covered_points(pharmacies, lat_min, lat_max, lon_min, lon_max)
                st.session_state.pharmacies = pharmacies
                st.session_state.non_covered_points = non_covered_points
                st.session_state.total_requests = total_requests
                center_lat = (lat_min + lat_max) / 2
                center_lon = (lon_min + lon_max) / 2
                st.session_state.map = self._create_map(pharmacies, non_covered_points, center_lat, center_lon,
                                                        st.session_state.map_zoom)
                st.session_state.map_center = {'lat': center_lat, 'lng': center_lon}
                st.session_state.selected_pharmacies = pharmacies
                st.session_state.selected_pharmacies_key = generate_pharmacies_key(pharmacies)

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
                self.storage_service.save_search_history(search_data)
                self.storage_service.increment_total_requests(user_id, total_requests)
                if not st.session_state.is_admin:
                    st.session_state.search_history = self.storage_service.load_search_history(user_id)
                else:
                    st.session_state.search_history = self.storage_service.load_search_history()
                st.session_state.search_in_progress = False
                st.session_state.page = "Résultats"
                logger.info(f"Recherche terminée : {len(pharmacies)} pharmacies trouvées, "
                            f"{len(non_covered_points)} points non couverts, "
                            f"{total_requests} requêtes, selected_pharmacies_key={st.session_state.selected_pharmacies_key}")
        except Exception as e:
            st.error(f"Erreur lors du lancement de la recherche : {e}")
            logger.error(f"Erreur lors du lancement de la recherche : {e}")
            self._reset_search()

    def _reset_search(self):
        """Réinitialiser l'état après une recherche échouée."""
        st.session_state.search_in_progress = False
        st.session_state.page = "Sélection de la zone"
        st.session_state.map = None
        st.session_state.selected_pharmacies_key = None
        st.session_state.show_non_covered = False
        logger.info("État réinitialisé : search_in_progress=False, map=None, selected_pharmacies_key=None")

    def _render_results_page(self):
        """Afficher la page des résultats."""
        st.header("Résultats de la recherche")
        logger.info("Affichage de la page Résultats")

        required_keys = ["bounds", "search_type", "pharmacies", "non_covered_points", "total_requests", "search_name"]
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
        st.write(f"Nombre total de points non couverts : {len(st.session_state.non_covered_points)}")
        st.write(f"Nombre total de requêtes effectuées : {st.session_state.total_requests}")

        st.checkbox("Afficher les zones non couvertes",
                    value=st.session_state.show_non_covered,
                    key="show_non_covered",
                    on_change=lambda: setattr(st.session_state, 'show_non_covered',
                                              not st.session_state.show_non_covered))
        st.info("Les zones non couvertes (cercles rouges) indiquent des emplacements potentiels pour une nouvelle pharmacie.")

        with st.container():
            if st.session_state.map is None:
                center_lat = st.session_state.map_center['lat']
                center_lon = st.session_state.map_center['lng']
                selected_pharmacies = st.session_state.get("selected_pharmacies", st.session_state.pharmacies)
                non_covered_points = st.session_state.get("non_covered_points", [])
                st.session_state.map = self._create_map(selected_pharmacies, non_covered_points, center_lat, center_lon,
                                                        st.session_state.map_zoom)
                st.session_state.selected_pharmacies_key = generate_pharmacies_key(selected_pharmacies)
                logger.info(f"Carte régénérée : {len(selected_pharmacies)} cercles, "
                            f"{len(non_covered_points)} points non couverts, "
                            f"selected_pharmacies_key={st.session_state.selected_pharmacies_key}")

            if st.session_state.selected_pharmacies_key:
                logger.info(f"Affichage de la carte avec selected_pharmacies_key={st.session_state.selected_pharmacies_key}")
                map_data = st_folium(st.session_state.map, width=MAP_WIDTH, height=MAP_HEIGHT,
                                     key=f"results_map_{st.session_state.selected_pharmacies_key}")
                if map_data and "center" in map_data and "zoom" in map_data and map_data["center"] and map_data["zoom"]:
                    st.session_state.map_center = map_data["center"]
                    st.session_state.map_zoom = map_data["zoom"]
                    logger.info(f"Interaction avec la carte : map_center={st.session_state.map_center}, "
                                f"map_zoom={st.session_state.map_zoom}")

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
                }
                </style>
                """,
                unsafe_allow_html=True
            )
            with st.container():
                st.markdown('<div class="pharmacy-list">', unsafe_allow_html=True)
                selected_pharmacies = []
                for i, pharmacy in enumerate(st.session_state.pharmacies):
                    if st.checkbox(pharmacy['name'], key=f"pharmacy_{i}", value=True):
                        selected_pharmacies.append(pharmacy)
                st.markdown('</div>', unsafe_allow_html=True)

        if st.button("Recalculer"):
            st.session_state.selected_pharmacies = selected_pharmacies
            non_covered_points = self._find_non_covered_points(selected_pharmacies, lat_min, lat_max, lon_min, lon_max)
            st.session_state.non_covered_points = non_covered_points
            st.session_state.selected_pharmacies_key = generate_pharmacies_key(selected_pharmacies)
            center_lat = st.session_state.map_center['lat']
            center_lon = st.session_state.map_center['lng']
            st.session_state.map = self._create_map(selected_pharmacies, non_covered_points, center_lat, center_lon,
                                                    st.session_state.map_zoom)
            logger.info(f"Carte mise à jour après recalcul : {len(selected_pharmacies)} cercles, "
                        f"{len(non_covered_points)} points non couverts, "
                        f"selected_pharmacies_key={st.session_state.selected_pharmacies_key}")

        df_pharmacies = pd.DataFrame(st.session_state.pharmacies)
        csv_pharmacies = df_pharmacies.to_csv(index=False)
        st.download_button(
            label="Télécharger la liste des pharmacies (CSV)",
            data=csv_pharmacies,
            file_name=f"pharmacies_{search_name}.csv",
            mime="text/csv"
        )
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

    def _render_billing_page(self):
        """Afficher la page de facturation."""
        st.header("Facturation")
        total_requests = self.storage_service.get_total_requests()
        st.write(f"Nombre total de requêtes effectuées (toutes sessions) : {total_requests}")
        st.write(f"Coût total estimé : {total_requests * 0.032:.2f}$")
        st.info("Ce coût est couvert par le crédit mensuel de 200$ de Google Maps Platform.")
        logger.info(f"Page Facturation : {total_requests} requêtes totales, coût estimé {total_requests * 0.032:.2f}$")

    def _render_history_page(self):
        """Afficher la page de l'historique des recherches."""
        st.header("Historique des recherches")
        logger.info("Affichage de la page Historique des recherches")

        user_id = st.session_state.username
        search_history = self.storage_service.load_search_history(user_id)
        st.session_state.search_history = search_history  # Mettre à jour l'historique

        if not search_history:
            st.info("Aucun historique de recherche disponible pour cet utilisateur.")
            logger.info(f"Aucun historique de recherche pour {user_id}")
            return

        st.subheader(f"Historique pour {user_id}")
        for search in search_history:
            with st.expander(f"Recherche : {search['name']} (Type : {search['search_type']})"):
                st.write(f"Date : {search.get('timestamp', 'Inconnue')}")
                st.write(f"Nombre de pharmacies : {len(search['pharmacies'])}")
                st.write(f"Requêtes API : {search['total_requests']}")
                mini_map = self._create_map(
                    search["pharmacies"],
                    search.get("non_covered_points", []),
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
                        st.session_state.map = self._create_map(
                            search["pharmacies"],
                            st.session_state.non_covered_points,
                            search["center_lat"],
                            search["center_lon"],
                            search["zoom"]
                        )
                        st.session_state.map_center = {'lat': search["center_lat"], 'lng': search["center_lon"]}
                        st.session_state.map_zoom = search["zoom"]
                        st.session_state.selected_pharmacies = search["pharmacies"]
                        st.session_state.selected_pharmacies_key = generate_pharmacies_key(search["pharmacies"])
                        st.session_state.show_non_covered = False
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

    def _render_user_management_page(self):
        """Afficher la page de gestion des utilisateurs."""
        st.header("Gestion des utilisateurs")
        logger.info("Affichage de la page Gestion des utilisateurs")

        st.subheader("Créer un nouvel utilisateur")
        new_username = st.text_input("Nom d'utilisateur", key="new_username")
        new_password = st.text_input("Mot de passe", type="password", key="new_password")
        initial_credits = st.number_input("Crédits initiaux", min_value=0, value=10, step=1)
        if st.button("Créer l'utilisateur"):
            if new_username and new_password:
                if self.user_service.create_user(new_username, new_password, initial_credits):
                    st.success(f"Utilisateur {new_username} créé avec {initial_credits} crédits.")
                else:
                    st.error(f"Erreur : l'utilisateur {new_username} existe déjà.")
            else:
                st.error("Erreur : veuillez entrer un nom d'utilisateur et un mot de passe.")
                logger.error("Tentative de création d'utilisateur avec des champs vides")

        st.subheader("Liste des utilisateurs")
        users = self.user_service.get_all_users()
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
                            if self.user_service.update_credits(username, new_credits):
                                st.success(f"Crédits mis à jour pour {username} : {new_credits} crédits.")
                    with col2:
                        if st.button(f"Supprimer {username}", key=f"delete_{username}"):
                            if self.user_service.delete_user(username):
                                st.success(f"Utilisateur {username} supprimé.")
                                st.rerun()

    def run(self):
        """Lancer l'application avec navigation et gestion de l'état."""
        # Initialisation des variables de session si elles n'existent pas
        if "is_authenticated" not in st.session_state:
            st.session_state.is_authenticated = False
            st.session_state.is_admin = False
            st.session_state.username = None
            st.session_state.page = "Connexion"
            st.session_state.search_history = []
            st.session_state.map = None
            st.session_state.search_in_progress = False
            st.session_state.map_center = DEFAULT_CENTER
            st.session_state.map_zoom = DEFAULT_ZOOM
            st.session_state.bounds = None
            st.session_state.search_type = None
            st.session_state.search_name = None
            st.session_state.pharmacies = []
            st.session_state.non_covered_points = []
            st.session_state.total_requests = 0
            st.session_state.selected_pharmacies = []
            st.session_state.selected_pharmacies_key = None
            st.session_state.show_non_covered = False
            st.session_state.subarea_step = None
            st.session_state.subarea_radius = None

        # Menu de navigation et bouton de déconnexion pour les utilisateurs authentifiés
        if st.session_state.is_authenticated:
            st.sidebar.title(f"Bienvenue, {st.session_state.username}")
            page_options = ["Sélection de la zone", "Résultats", "Historique"]
            if st.session_state.is_admin:
                page_options.extend(["Facturation", "Gestion des utilisateurs"])
            st.session_state.page = st.sidebar.selectbox("Naviguer", page_options, index=page_options.index(st.session_state.page))
            if st.sidebar.button("Déconnexion"):
                # Réinitialiser l'état de la session
                st.session_state.is_authenticated = False
                st.session_state.is_admin = False
                st.session_state.username = None
                st.session_state.page = "Connexion"
                st.session_state.search_history = []
                st.session_state.map = None
                st.session_state.search_in_progress = False
                st.session_state.map_center = DEFAULT_CENTER
                st.session_state.map_zoom = DEFAULT_ZOOM
                st.session_state.bounds = None
                st.session_state.search_type = None
                st.session_state.search_name = None
                st.session_state.pharmacies = []
                st.session_state.non_covered_points = []
                st.session_state.total_requests = 0
                st.session_state.selected_pharmacies = []
                st.session_state.selected_pharmacies_key = None
                st.session_state.show_non_covered = False
                st.session_state.subarea_step = None
                st.session_state.subarea_radius = None
                logger.info(f"Déconnexion de l'utilisateur {st.session_state.username}")
                st.rerun()

        # Navigation basée sur l'état de la page
        if not st.session_state.is_authenticated:
            self._render_login_page()
        elif st.session_state.page == "Sélection de la zone":
            self._render_selection_page()
        elif st.session_state.page == "Résultats":
            self._render_results_page()
        elif st.session_state.page == "Historique":
            self._render_history_page()
        elif st.session_state.page == "Facturation" and st.session_state.is_admin:
            self._render_billing_page()
        elif st.session_state.page == "Gestion des utilisateurs" and st.session_state.is_admin:
            self._render_user_management_page()


if __name__ == "__main__":
    from datetime import datetime
    app = PharmacyApp()
    app.run()
