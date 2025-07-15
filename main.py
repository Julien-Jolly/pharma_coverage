import streamlit as st
import logging
import boto3
import json
import mysql.connector
from mysql.connector import Error
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
from urllib.request import urlopen
import socket
import time

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
AWS_REGION = 'eu-west-3'  # Région AWS
DB_CONFIG_SECRET_NAME = 'pharmacy_app_db_config'
GOOGLE_API_SECRET_NAME = 'pharmacy_app_google_api'

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
        self.db_config = self._get_db_config()
        self.google_api_key = self._get_google_api_key()
        self._init_db()
        self.storage_service = StorageService(self.db_config)
        self.user_service = UserService(self.storage_service)
        self.pharmacy_service = PharmacyService(self.google_api_key)
        self._initialize_session_state()
        logger.info(f"Initialisation : page={st.session_state.get('page', 'non défini')}, "
                    f"search_in_progress={st.session_state.get('search_in_progress', 'non défini')}, "
                    f"map={'défini' if st.session_state.get('map') else 'non défini'}, "
                    f"map_center={st.session_state.get('map_center', 'non défini')}, "
                    f"map_zoom={st.session_state.get('map_zoom', 'non défini')}, "
                    f"search_history={len(st.session_state.get('search_history', []))} recherches, "
                    f"is_admin={st.session_state.get('is_admin', False)}, "
                    f"username={st.session_state.get('username', 'non défini')}, "
                    f"client_ip={st.session_state.get('client_ip', 'non défini')}")

    def _get_db_config(self):
        """Récupérer la configuration de la base de données depuis AWS Secrets Manager."""
        try:
            session = boto3.session.Session()
            client = session.client(service_name='secretsmanager', region_name=AWS_REGION)
            secret_value = client.get_secret_value(SecretId=DB_CONFIG_SECRET_NAME)
            secret = json.loads(secret_value['SecretString'])
            logger.info("Configuration de la base de données récupérée avec succès")
            return secret
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de la configuration de la base de données : {e}")
            raise Exception("Échec de la récupération de la configuration de la base de données")

    def _get_google_api_key(self):
        """Récupérer la clé API Google depuis AWS Secrets Manager."""
        try:
            session = boto3.session.Session()
            client = session.client(service_name='secretsmanager', region_name=AWS_REGION)
            secret_value = client.get_secret_value(SecretId=GOOGLE_API_SECRET_NAME)
            secret = json.loads(secret_value['SecretString'])
            api_key = secret.get('google_api_key')
            if not api_key:
                raise ValueError("Clé API Google non trouvée dans le secret")
            logger.info("Clé API Google récupérée avec succès")
            return api_key
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de la clé API Google : {e}")
            raise Exception("Échec de la récupération de la clé API Google")

    def _init_db(self):
        """Initialiser la connexion à la base de données et créer les tables nécessaires."""
        try:
            connection = mysql.connector.connect(**self.db_config)
            if connection.is_connected():
                cursor = connection.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        username VARCHAR(255) PRIMARY KEY,
                        password_hash VARCHAR(255) NOT NULL,
                        credits INT DEFAULT 10,
                        is_admin BOOLEAN DEFAULT FALSE
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS search_history (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id VARCHAR(255),
                        name VARCHAR(255),
                        bounds TEXT,
                        search_type VARCHAR(50),
                        subarea_step FLOAT,
                        subarea_radius FLOAT,
                        pharmacies TEXT,
                        total_requests INT,
                        map_html TEXT,
                        center_lat FLOAT,
                        center_lon FLOAT,
                        zoom INT,
                        timestamp DATETIME,
                        FOREIGN KEY (user_id) REFERENCES users(username)
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS active_ips (
                        ip VARCHAR(45) PRIMARY KEY,
                        last_seen DATETIME
                    )
                """)
                connection.commit()
                logger.info("Base de données initialisée avec succès")
            else:
                logger.error("Échec de la connexion à la base de données")
                raise Exception("Échec de la connexion à la base de données")
        except Error as e:
            logger.error(f"Erreur lors de l'initialisation de la base de données : {e}")
            raise
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

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
            'total_requests': 0,
            'selected_pharmacies': [],
            'subarea_step': None,
            'subarea_radius': None,
            'area_too_large': False,
            'zone_validated': False,
            'client_ip': self._get_client_ip()
        }
        for key, value in defaults.items():
            if key not in st.session_state:
                st.session_state[key] = value
        logger.info(f"État de la session initialisé : map_center={st.session_state.get('map_center')}, map_zoom={st.session_state.get('map_zoom')}, client_ip={st.session_state.get('client_ip')}")

    def _get_client_ip(self):
        """Obtenir l'adresse IP du client."""
        try:
            ip = urlopen('https://api.ipify.org').read().decode('utf-8')
            logger.info(f"Adresse IP du client obtenue : {ip}")
            self._update_active_ip(ip)
            return ip
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de l'IP du client : {e}")
            return socket.gethostbyname(socket.gethostname())

    def _update_active_ip(self, ip):
        """Mettre à jour la table des IPs actives."""
        try:
            connection = mysql.connector.connect(**self.db_config)
            cursor = connection.cursor()
            cursor.execute("""
                INSERT INTO active_ips (ip, last_seen) 
                VALUES (%s, NOW()) 
                ON DUPLICATE KEY UPDATE last_seen = NOW()
            """, (ip,))
            connection.commit()
            logger.info(f"IP {ip} mise à jour dans la base de données")
        except Error as e:
            logger.error(f"Erreur lors de la mise à jour de l'IP active : {e}")
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    def _reset_map_state(self):
        """Réinitialiser les variables de session liées à la carte."""
        st.session_state.map = None
        st.session_state.bounds = None
        st.session_state.area_too_large = False
        st.session_state.selected_pharmacies = []
        st.session_state.selected_pharmacies_key = None
        st.session_state.pharmacies = []
        st.session_state.search_name = None
        st.session_state.search_type = None
        st.session_state.subarea_step = None
        st.session_state.subarea_radius = None
        st.session_state.total_requests = 0
        st.session_state.zone_validated = False
        st.session_state.map_center = DEFAULT_CENTER
        st.session_state.map_zoom = DEFAULT_ZOOM
        logger.info("État de la carte réinitialisé")

    def run(self):
        """Lancer l'application avec navigation et gestion de l'état."""
        # Forcer l'initialisation de l'état de la session
        self._initialize_session_state()
        logger.info(f"État de la session dans run() : map_center={st.session_state.get('map_center', 'non défini')}, map_zoom={st.session_state.get('map_zoom', 'non défini')}, client_ip={st.session_state.get('client_ip', 'non défini')}")

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
                width: 100%;
                margin: 5px 0;
            }
            .stButton>button:hover {
                background-color: #45a049;
            }
            .stTextInput>input {
                border: 1px solid #ccc;
                border-radius: 5px;
                padding: 8px;
                margin: 5px 0;
            }
            .stRadio>label {
                font-weight: bold;
            }
            .stSidebar .sidebar-content {
                background-color: #ffffff;
                border-right: 1px solid #ddd;
                padding: 15px;
            }
            .stSidebar h3 {
                color: #333;
                font-family: 'Arial', sans-serif;
                margin-bottom: 10px;
            }
            .stSidebar hr {
                border: 0;
                border-top: 1px solid #eee;
                margin: 10px 0;
            }
            .stSidebar .stTextInput>input {
                border: 2px solid #4CAF50;
                border-radius: 5px;
                padding: 10px;
                margin-bottom: 10px;
            }
            .stSidebar .stButton>button {
                background-color: #4CAF50;
                color: white;
                border-radius: 5px;
                padding: 10px;
                margin: 5px 0;
                font-size: 14px;
            }
            .stSidebar .stButton>button:disabled {
                background-color: #cccccc;
                color: #666666;
            }
            .stSidebar .stDownloadButton>button {
                background-color: #2196F3;
                color: white;
                border-radius: 5px;
                padding: 10px;
                margin: 5px 0;
                font-size: 14px;
            }
            .stSidebar .stDownloadButton>button:hover {
                background-color: #1976D2;
            }
            .stSidebar .stCheckbox {
                margin: 5px 0;
            }
            .stSidebar .pharmacy-list {
                max-height: 300px;
                overflow-y: auto;
                padding: 10px;
                border: 1px solid #ccc;
                border-radius: 5px;
                background-color: #f9f9f9;
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
            .st-folium-map { z-index: 1; }
            </style>
        """, unsafe_allow_html=True)

        # Menu de navigation et bouton de déconnexion
        if st.session_state.is_authenticated:
            st.sidebar.title(f"Bienvenue, {st.session_state.username}")
            page_options = ["Sélection de la zone", "Résultats", "Historique"]
            if st.session_state.is_admin:
                page_options.extend(["Facturation", "Gestion des utilisateurs"])
            current_page = st.session_state.get('page', 'Connexion')
            # Corriger si la page actuelle n'est pas dans les options
            if current_page not in page_options:
                logger.warning(f"Page invalide : {current_page}, réinitialisation à 'Sélection de la zone'")
                current_page = "Sélection de la zone"
                st.session_state.page = current_page
            new_page = st.sidebar.selectbox("Naviguer", page_options, index=page_options.index(current_page), key="nav_select")
            if new_page != current_page:
                logger.info(f"Tentative de changement de page : de {current_page} à {new_page}")
                if new_page == "Sélection de la zone":
                    self._reset_map_state()
                st.session_state.page = new_page
                st.rerun()

            if st.sidebar.button("Déconnexion"):
                try:
                    for key in list(st.session_state.keys()):
                        del st.session_state[key]
                    st.session_state.is_authenticated = False
                    st.session_state.is_admin = False
                    st.session_state.username = None
                    st.session_state.page = "Connexion"
                    self._initialize_session_state()  # Réinitialiser après déconnexion
                    logger.info("Déconnexion effectuée")
                    st.rerun()
                except Exception as e:
                    logger.error(f"Erreur lors de la déconnexion : {e}")
                    st.error("Erreur lors de la déconnexion. Veuillez réessayer.")

        # Navigation basée sur l'état de la page
        logger.info(f"Rendu de la page : {st.session_state.get('page', 'non défini')}")
        if not st.session_state.is_authenticated:
            render_login_page(self)
        elif st.session_state.page == "Sélection de la zone":
            logger.info(f"Avant render_selection_page : map_center={st.session_state.get('map_center', 'non défini')}, map_zoom={st.session_state.get('map_zoom', 'non défini')}, client_ip={st.session_state.get('client_ip', 'non défini')}")
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
    try:
        app = PharmacyApp()
        app.run()
    except Exception as e:
        logger.error(f"Erreur critique lors du démarrage de l'application : {e}")
        st.error("Une erreur critique s'est produite lors du démarrage de l'application. Veuillez vérifier les journaux pour plus de détails.")