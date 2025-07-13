import streamlit as st
import logging
from pages import (
    render_login_page,
    render_selection_page,
    render_results_page,
    render_billing_page,
    render_history_page,
    render_user_management_page
)
from services.pharmacy_service import PharmacyService
from services.storage_service import StorageService
from services.user_services import UserService

# Configurer les journaux
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
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
NON_COVERED_RADIUS = 100

class PharmacyApp:
    """Application Streamlit pour la recherche de pharmacies et gestion des utilisateurs."""

    def __init__(self):
        """Initialiser l'application et les services."""
        st.set_page_config(
            page_title="Pharmacy Coverage",
            page_icon="💊",
            layout="wide",
            initial_sidebar_state="expanded"
        )
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
            'subarea_radius': None,
            'area_too_large': False
        }
        for key, value in defaults.items():
            if key not in st.session_state:
                st.session_state[key] = value

    def run(self):
        """Lancer l'application avec navigation et gestion de l'état."""
        # Injecter CSS personnalisé pour améliorer l'apparence
        st.markdown("""
            <style>
            .main { background-color: #f5f5f5; padding: 20px; }
            .stButton>button {
                background-color: #4CAF50;
                color: white;
                border-radius: 5px;
                padding: 10px 20px;
                font-weight: bold;
            }
            .stButton>button:hover {
                background-color: #45a049;
            }
            .stTextInput>input {
                border: 1px solid #ccc;
                border-radius: 5px;
                padding: 8px;
            }
            .stRadio>label {
                font-weight: bold;
            }
            .sidebar .sidebar-content {
                background-color: #ffffff;
                border-right: 1px solid #ddd;
            }
            h1, h2, h3 {
                color: #333;
                font-family: 'Arial', sans-serif;
            }
            .error-overlay {
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background-color: rgba(255, 0, 0, 0.2);
                z-index: 1000;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-size: 18px;
                font-weight: bold;
            }
            </style>
        """, unsafe_allow_html=True)

        # Menu de navigation et bouton de déconnexion
        if st.session_state.is_authenticated:
            st.sidebar.title(f"Bienvenue, {st.session_state.username}")
            page_options = ["Sélection de la zone", "Résultats", "Historique"]
            if st.session_state.is_admin:
                page_options.extend(["Facturation", "Gestion des utilisateurs"])
            st.session_state.page = st.sidebar.selectbox("Naviguer", page_options, index=page_options.index(st.session_state.page))
            if st.sidebar.button("Déconnexion"):
                # Réinitialiser l'état de la session
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.session_state.is_authenticated = False
                st.session_state.is_admin = False
                st.session_state.username = None
                st.session_state.page = "Connexion"
                logger.info("Déconnexion effectuée")
                st.rerun()

        # Navigation basée sur l'état de la page
        if not st.session_state.is_authenticated:
            render_login_page(self)
        elif st.session_state.page == "Sélection de la zone":
            render_selection_page(self)
        elif st.session_state.page == "Résultats":
            render_results_page(self)
        elif st.session_state.page == "Historique":
            render_history_page(self)
        elif st.session_state.page == "Facturation" and st.session_state.is_admin:
            render_billing_page(self)
        elif st.session_state.page == "Gestion des utilisateurs" and st.session_state.is_admin:
            render_user_management_page(self)

if __name__ == "__main__":
    app = PharmacyApp()
    app.run()