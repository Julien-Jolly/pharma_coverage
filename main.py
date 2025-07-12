import streamlit as st
import folium
import pandas as pd
from streamlit_folium import st_folium
import logging
from services.pharmacy_service import PharmacyService
from services.storage_service import StorageService
from utils.helpers import estimate_bounds, generate_pharmacies_key

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


class PharmacyApp:
    """Application Streamlit pour la recherche de pharmacies."""

    def __init__(self):
        """Initialiser l'application et les services."""
        self.storage_service = StorageService()
        self.pharmacy_service = PharmacyService()
        self._initialize_session_state()
        logger.info(f"Initialisation : page={st.session_state.page}, "
                    f"search_in_progress={st.session_state.search_in_progress}, "
                    f"map={'défini' if st.session_state.map else 'non défini'}, "
                    f"map_center={st.session_state.map_center}, "
                    f"map_zoom={st.session_state.map_zoom}, "
                    f"search_history={len(st.session_state.search_history)} recherches, "
                    f"selected_pharmacies_key={st.session_state.selected_pharmacies_key}")

    def _initialize_session_state(self):
        """Initialiser les variables de session."""
        defaults = {
            'page': "Sélection de la zone",
            'search_in_progress': False,
            'map': None,
            'map_center': DEFAULT_CENTER,
            'map_zoom': DEFAULT_ZOOM,
            'search_history': self.storage_service.load_search_history(),
            'selected_pharmacies_key': None
        }
        for key, value in defaults.items():
            if key not in st.session_state:
                st.session_state[key] = value

    def _create_map(self, pharmacies, center_lat, center_lon, zoom, width=MAP_WIDTH, height=MAP_HEIGHT):
        """Créer une carte Folium avec des cercles de 300m et popup."""
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
        logger.info(f"Carte créée : {len(pharmacies)} cercles de {CIRCLE_RADIUS}m, "
                    f"center=({center_lat:.4f}, {center_lon:.4f}), zoom={zoom}, "
                    f"width={width}, height={height}")
        return m

    def _render_selection_page(self):
        """Afficher la page de sélection de la zone."""
        st.header("Sélection de la zone de recherche")
        st.write("Ajustez la carte (zoom/déplacement) pour définir la zone visible.")

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
                        st.session_state.bounds = (lat_min, lat_max, lon_min, lon_max)
                        st.write(f"Zone validée : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, "
                                 f"lon_min={lon_min:.4f}, lon_max={lon_max:.4f}")
                        logger.info(f"Zone validée : lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, "
                                    f"lon_min={lon_min:.4f}, lon_max={lon_max:.4f}")
                        st.session_state.search_in_progress = False
                    else:
                        st.error("Erreur : les coordonnées de la zone sont invalides.")
                        logger.error("Coordonnées de la zone invalides")
                except (KeyError, TypeError) as e:
                    logger.warning(f"Erreur lors de la récupération des limites : {e}")
                    center = map_data.get("center", DEFAULT_CENTER)
                    zoom = map_data.get("zoom", DEFAULT_ZOOM)
                    lat_min, lat_max, lon_min, lon_max = estimate_bounds(center["lat"], center["lng"], zoom)
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
                subarea_step = 0.01 if "rapide" in search_type.lower() else 0.005
                subarea_radius = 1000 if "rapide" in search_type.lower() else 500

                estimated_subareas = len(list(product(
                    np.arange(lat_min, lat_max, subarea_step),
                    np.arange(lon_min, lon_max, subarea_step)
                )))
                st.warning(f"Cette recherche peut générer ~{estimated_subareas} requêtes, "
                           f"coût estimé : {estimated_subareas * 0.032:.2f}$")
                logger.info(f"Estimation : {estimated_subareas} sous-zones, coût ~{estimated_subareas * 0.032:.2f}$")

                if st.button("Lancer la recherche"):
                    if not search_name:
                        st.error("Erreur : veuillez entrer un nom pour la recherche.")
                        logger.error("Nom de recherche vide")
                    elif not self.storage_service.is_search_name_unique(search_name):
                        st.error(f"Erreur : le nom '{search_name}' est déjà utilisé.")
                        logger.error(f"Nom de recherche '{search_name}' déjà utilisé")
                    else:
                        self._process_search(lat_min, lat_max, lon_min, lon_max,
                                             subarea_step, subarea_radius, search_name)

    def _process_search(self, lat_min, lat_max, lon_min, lon_max, subarea_step, subarea_radius, search_name):
        """Traiter la recherche de pharmacies."""
        logger.info(f"Lancement de la recherche : name={search_name}, step={subarea_step}, radius={subarea_radius}")
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
                st.session_state.pharmacies = pharmacies
                st.session_state.total_requests = total_requests
                center_lat = (lat_min + lat_max) / 2
                center_lon = (lon_min + lon_max) / 2
                st.session_state.map = self._create_map(pharmacies, center_lat, center_lon,
                                                        st.session_state.map_zoom)
                st.session_state.map_center = {'lat': center_lat, 'lng': center_lon}
                st.session_state.selected_pharmacies = pharmacies
                st.session_state.selected_pharmacies_key = generate_pharmacies_key(pharmacies)

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
                self.storage_service.save_search_history(search_data)
                st.session_state.search_in_progress = False
                st.session_state.page = "Résultats"
                logger.info(f"Recherche terminée : {len(pharmacies)} pharmacies trouvées, "
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
        logger.info("État réinitialisé : search_in_progress=False, map=None, selected_pharmacies_key=None")

    def _render_results_page(self):
        """Afficher la page des résultats."""
        st.header("Résultats de la recherche")
        logger.info("Affichage de la page Résultats")

        if not all(key in st.session_state for key in ["bounds", "search_type", "pharmacies"]):
            st.error("Aucune zone sélectionnée ou résultats définis. Retournez à la page de sélection.")
            logger.error("Aucune zone, type de recherche ou résultats définis")
            self._reset_search()
            return

        lat_min, lat_max, lon_min, lon_max = st.session_state.bounds
        search_name = st.session_state.get("search_name", "Recherche sans nom")
        logger.info(f"Paramètres : name={search_name}, lat_min={lat_min:.4f}, lat_max={lat_max:.4f}, "
                    f"lon_min={lon_min:.4f}, lon_max={lon_max:.4f}, "
                    f"step={st.session_state.subarea_step}, radius={st.session_state.subarea_radius}")

        with st.container():
            if st.session_state.map is None:
                center_lat = st.session_state.map_center['lat']
                center_lon = st.session_state.map_center['lng']
                selected_pharmacies = st.session_state.get("selected_pharmacies", st.session_state.pharmacies)
                st.session_state.map = self._create_map(selected_pharmacies, center_lat, center_lon,
                                                        st.session_state.map_zoom)
                st.session_state.selected_pharmacies_key = generate_pharmacies_key(selected_pharmacies)
                logger.info(f"Carte régénérée : {len(selected_pharmacies)} cercles, "
                            f"selected_pharmacies_key={st.session_state.selected_pharmacies_key}")

            if st.session_state.selected_pharmacies_key:
                logger.info(
                    f"Affichage de la carte avec selected_pharmacies_key={st.session_state.selected_pharmacies_key}")
                map_data = st_folium(st.session_state.map, width=MAP_WIDTH, height=MAP_HEIGHT,
                                     key=f"results_map_{st.session_state.selected_pharmacies_key}")
                if map_data and "center" in map_data and "zoom" in map_data and map_data["center"] and map_data["zoom"]:
                    st.session_state.map_center = map_data["center"]
                    st.session_state.map_zoom = map_data["zoom"]
                    logger.info(f"Interaction avec la carte : map_center={st.session_state.map_center}, "
                                f"map_zoom={st.session_state.map_zoom}, aucune régénération")

        st.write(f"Nom de la recherche : {search_name}")
        st.write(f"Nombre total de pharmacies trouvées : {len(st.session_state.pharmacies)}")
        st.write(f"Nombre total de requêtes effectuées : {st.session_state.total_requests}")

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
            st.session_state.selected_pharmacies_key = generate_pharmacies_key(selected_pharmacies)
            center_lat = st.session_state.map_center['lat']
            center_lon = st.session_state.map_center['lng']
            st.session_state.map = self._create_map(selected_pharmacies, center_lat, center_lon,
                                                    st.session_state.map_zoom)
            logger.info(f"Carte mise à jour après recalcul : {len(selected_pharmacies)} cercles, "
                        f"selected_pharmacies_key={st.session_state.selected_pharmacies_key}")

        df_pharmacies = pd.DataFrame(st.session_state.pharmacies)
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

        if not st.session_state.search_history:
            st.info("Aucun historique de recherche disponible.")
            logger.info("Aucun historique de recherche")
        else:
            for search in st.session_state.search_history:
                st.subheader(f"Recherche : {search['name']}")
                mini_map = self._create_map(search["pharmacies"], search["center_lat"],
                                            search["center_lon"], search["zoom"],
                                            width=MINI_MAP_WIDTH, height=MINI_MAP_HEIGHT)
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
                        st.session_state.total_requests = search["total_requests"]
                        st.session_state.search_name = search["name"]
                        st.session_state.map = self._create_map(search["pharmacies"],
                                                                search["center_lat"],
                                                                search["center_lon"],
                                                                search["zoom"])
                        st.session_state.map_center = {'lat': search["center_lat"], 'lng': search["center_lon"]}
                        st.session_state.map_zoom = search["zoom"]
                        st.session_state.selected_pharmacies = search["pharmacies"]
                        st.session_state.selected_pharmacies_key = generate_pharmacies_key(search["pharmacies"])
                        st.session_state.page = "Résultats"
                        logger.info(f"Visualisation de la recherche '{search['name']}': "
                                    f"passage à la page Résultats, "
                                    f"selected_pharmacies_key={st.session_state.selected_pharmacies_key}")
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

    def run(self):
        """Exécuter l'application."""
        st.sidebar.title("Navigation")
        page = st.sidebar.selectbox("Choisir une page",
                                    ["Sélection de la zone", "Résultats", "Facturation", "Historique des recherches"],
                                    index=["Sélection de la zone", "Résultats", "Facturation",
                                           "Historique des recherches"].index(st.session_state.page))
        if page != st.session_state.page:
            logger.info(f"Mise à jour de la page : de {st.session_state.page} à {page}")
            st.session_state.page = page
            st.session_state.search_in_progress = False
            if page == "Sélection de la zone":
                st.session_state.map = None
                st.session_state.map_center = DEFAULT_CENTER
                st.session_state.map_zoom = DEFAULT_ZOOM
                st.session_state.selected_pharmacies_key = None
                logger.info("Réinitialisation pour Sélection de la zone")

        if st.session_state.page == "Sélection de la zone":
            self._render_selection_page()
        elif st.session_state.page == "Résultats":
            self._render_results_page()
        elif st.session_state.page == "Facturation":
            self._render_billing_page()
        elif st.session_state.page == "Historique des recherches":
            self._render_history_page()


if __name__ == "__main__":
    app = PharmacyApp()
    app.run()