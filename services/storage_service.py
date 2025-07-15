import boto3
from botocore.exceptions import ClientError
import streamlit as st
import json
import logging
from datetime import datetime, timedelta
import mysql.connector
from mysql.connector import Error
import os

logger = logging.getLogger(__name__)

# Configuration AWS
default_region = os.getenv('AWS_REGION', 'eu-north-1')
secrets_client = boto3.client('secretsmanager', region_name=default_region)

try:
    secret = secrets_client.get_secret_value(SecretId='pharmacy-app-secrets')
    secrets = json.loads(secret['SecretString'])

    # Vérification des clés critiques
    required_keys = ['mysql', 'AWS_REGION', 'GOOGLE_API_KEY']
    missing_keys = [key for key in required_keys if key not in secrets or not secrets[key]]
    if missing_keys:
        logger.error(f"Clés manquantes dans le secret : {missing_keys}")
        st.error(f"Erreur : clés manquantes dans le secret AWS : {missing_keys}")
        raise ValueError(f"Clés manquantes dans le secret : {missing_keys}")

    db_config = secrets['mysql']
    aws_region = secrets['AWS_REGION']
    google_api_key = secrets['GOOGLE_API_KEY']
    aws_access_key_id = secrets.get('AWS_ACCESS_KEY_ID', st.secrets.get('AWS_ACCESS_KEY_ID', ''))
    aws_secret_access_key = secrets.get('AWS_SECRET_ACCESS_KEY', st.secrets.get('AWS_SECRET_ACCESS_KEY', ''))
    s3_bucket_name = secrets.get('S3_BUCKET_NAME', st.secrets.get('S3_BUCKET_NAME', ''))
    admin_password = secrets.get('ADMIN_PASSWORD', st.secrets.get('ADMIN_PASSWORD', ''))
    security_group_id = secrets.get('RDS_SECURITY_GROUP_ID', '')

    # Vérification des clés MySQL
    required_mysql_keys = ['host', 'port', 'database', 'user', 'password']
    missing_mysql_keys = [key for key in required_mysql_keys if key not in db_config or not db_config[key]]
    if missing_mysql_keys:
        logger.error(f"Clés MySQL manquantes : {missing_mysql_keys}")
        st.error(f"Erreur : clés MySQL manquantes dans le secret : {missing_mysql_keys}")
        raise ValueError(f"Clés MySQL manquantes : {missing_mysql_keys}")

    if aws_region != default_region:
        logger.warning(f"Région par défaut ({default_region}) diffère de la région des secrets ({aws_region}).")
except ClientError as e:
    error_code = e.response['Error']['Code']
    error_message = e.response['Error']['Message']
    logger.error(f"Erreur AWS Secrets Manager ({error_code}): {error_message}")
    st.error(
        f"Erreur lors du chargement du secret 'pharmacy-app-secrets' : {error_code} - {error_message}. Vérifiez le nom du secret et les permissions IAM.")
    raise
except Exception as e:
    logger.error(f"Erreur inattendue lors du chargement des secrets : {e}")
    st.error(f"Erreur inattendue lors du chargement des secrets : {e}. Vérifiez votre configuration AWS.")
    raise


class StorageService:
    def __init__(self):
        """Initialiser le service de stockage avec S3 et MySQL."""
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=aws_region
        )
        self.bucket_name = s3_bucket_name
        logger.info("Connexion S3 et MySQL initialisée")

    def _get_db_connection(self):
        """Créer une connexion MySQL avec gestionnaire de contexte."""
        try:
            return mysql.connector.connect(
                host=db_config['host'],
                port=db_config['port'],
                database=db_config['database'],
                user=db_config['user'],
                password=db_config['password']
            )
        except Error as e:
            logger.error(f"Erreur de connexion à MySQL : {e}")
            st.error(f"Erreur de connexion à la base de données : {e}")
            raise

    def save_active_ip(self, ip_address):
        """Enregistrer une IP active avec une expiration de 24h."""
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                expires_at = datetime.now() + timedelta(days=1)
                cursor.execute(
                    """
                    INSERT INTO ACTIVE_IPS (ip_address, added_at, expires_at)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE added_at = %s, expires_at = %s
                    """,
                    (ip_address, datetime.now(), expires_at, datetime.now(), expires_at)
                )
                conn.commit()
                logger.info(f"IP active enregistrée : {ip_address}, expire le {expires_at}")
        except Error as e:
            logger.error(f"Erreur lors de l'enregistrement de l'IP active {ip_address} : {e}")
            st.error("Erreur lors de l'enregistrement de l'IP active.")
            raise

    def get_active_ips(self):
        """Récupérer la liste des IPs actives non expirées."""
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT ip_address FROM ACTIVE_IPS WHERE expires_at > NOW()")
                active_ips = [row[0] for row in cursor.fetchall()]
                logger.info(f"IPs actives récupérées : {len(active_ips)} IPs")
                return active_ips
        except Error as e:
            logger.error(f"Erreur lors de la récupération des IPs actives : {e}")
            st.error("Erreur lors de la récupération des IPs actives.")
            return []

    def load_users(self):
        """Charger les utilisateurs depuis la base de données."""
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT username, password, credits, is_admin FROM USERS")
                users = {row[0]: {"password": row[1], "credits": row[2], "is_admin": row[3]} for row in
                         cursor.fetchall()}
                logger.info(f"Utilisateurs chargés : {len(users)} utilisateurs")
                return users
        except Error as e:
            logger.error(f"Erreur lors du chargement des utilisateurs : {e}")
            st.error("Erreur lors du chargement des utilisateurs.")
            return {}

    def save_users(self, users):
        """Enregistrer les utilisateurs dans la base de données."""
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                for username, data in users.items():
                    cursor.execute(
                        "INSERT INTO USERS (username, password, credits, is_admin) VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE password=VALUES(password), credits=VALUES(credits), is_admin=VALUES(is_admin)",
                        (username, data['password'], data['credits'], data.get('is_admin', False))
                    )
                conn.commit()
                logger.info("Utilisateurs enregistrés dans MySQL")
        except Error as e:
            logger.error(f"Erreur lors de la sauvegarde des utilisateurs : {e}")
            st.error("Erreur lors de la sauvegarde des utilisateurs.")
            raise

    def load_search_history(self, user_id=None):
        """Charger l'historique des recherches pour un utilisateur ou tous les utilisateurs (admin)."""
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                query = """
                    SELECT id, name, user_id, bounds, search_type, subarea_step, subarea_radius,
                           total_requests, map_html, center_lat, center_lon, zoom, timestamp
                    FROM SEARCH_HISTORY
                """
                params = []
                if user_id and user_id != "admin":
                    query += " WHERE user_id = %s"
                    params.append(user_id)
                cursor.execute(query, params)
                history = []
                for row in cursor.fetchall():
                    search_id = row[0]
                    cursor.execute("""
                        SELECT p.name, p.address, p.latitude, p.longitude
                        FROM PHARMACIES p
                        JOIN SEARCH_PHARMACIES sp ON p.id = sp.pharmacy_id
                        WHERE sp.search_id = %s
                    """, (search_id,))
                    pharmacies = [{"name": row[0], "address": row[1], "latitude": row[2], "longitude": row[3]} for row
                                  in cursor.fetchall()]
                    history.append({
                        "name": row[1],
                        "user_id": row[2],
                        "bounds": json.loads(row[3]),
                        "search_type": row[4],
                        "subarea_step": row[5],
                        "subarea_radius": row[6],
                        "total_requests": row[7],
                        "map_html": row[8],
                        "center_lat": row[9],
                        "center_lon": row[10],
                        "zoom": row[11],
                        "timestamp": row[12],
                        "pharmacies": pharmacies
                    })
                logger.info(f"Historique chargé : {len(history)} recherches" + (
                    f" pour l'utilisateur {user_id}" if user_id else ""))
                return history
        except Error as e:
            logger.error(f"Erreur lors du chargement de l'historique : {e}")
            st.error("Erreur lors du chargement de l'historique.")
            return []

    def save_search_history(self, search_data):
        """Enregistrer une recherche dans l'historique."""
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO USERS (username, password, credits, is_admin) VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE credits=credits",
                    (search_data['user_id'], "", 0, False)
                )
                cursor.execute(
                    """
                    INSERT INTO SEARCH_HISTORY (name, user_id, bounds, search_type, subarea_step, subarea_radius,
                                                total_requests, map_html, center_lat, center_lon, zoom, timestamp)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        search_data['name'],
                        search_data['user_id'],
                        json.dumps(search_data['bounds']),
                        search_data['search_type'],
                        search_data['subarea_step'],
                        search_data['subarea_radius'],
                        search_data['total_requests'],
                        search_data['map_html'],
                        search_data['center_lat'],
                        search_data['center_lon'],
                        search_data['zoom'],
                        search_data['timestamp']
                    )
                )
                search_id = cursor.lastrowid
                for pharmacy in search_data['pharmacies']:
                    cursor.execute(
                        "INSERT IGNORE INTO PHARMACIES (name, address, latitude, longitude) VALUES (%s, %s, %s, %s)",
                        (pharmacy['name'], pharmacy.get('address'), pharmacy['latitude'], pharmacy['longitude'])
                    )
                    cursor.execute(
                        "SELECT id FROM PHARMACIES WHERE name = %s AND latitude = %s AND longitude = %s",
                        (pharmacy['name'], pharmacy['latitude'], pharmacy['longitude'])
                    )
                    pharmacy_id = cursor.fetchone()[0]
                    cursor.execute(
                        "INSERT IGNORE INTO SEARCH_PHARMACIES (search_id, pharmacy_id) VALUES (%s, %s)",
                        (search_id, pharmacy_id)
                    )
                conn.commit()
                logger.info(f"Recherche sauvegardée : {search_data['name']}")
        except Error as e:
            logger.error(f"Erreur lors de la sauvegarde de l'historique : {e}")
            st.error("Erreur lors de la sauvegarde de l'historique.")
            raise

    def is_search_name_unique(self, search_name, user_id=None):
        """Vérifier si le nom de recherche est unique pour un utilisateur."""
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                query = "SELECT name FROM SEARCH_HISTORY"
                params = []
                if user_id and user_id != "admin":
                    query += " WHERE user_id = %s AND name = %s"
                    params = [user_id, search_name]
                else:
                    query += " WHERE name = %s"
                    params = [search_name]
                cursor.execute(query, params)
                result = cursor.fetchone()
                return result is None
        except Error as e:
            logger.error(f"Erreur lors de la vérification de l'unicité du nom de recherche : {e}")
            return False

    def get_total_requests(self, user_id=None):
        """Obtenir le nombre total de requêtes pour un utilisateur ou tous les utilisateurs."""
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                if user_id:
                    cursor.execute("SELECT total_requests FROM USERS WHERE username = %s", (user_id,))
                    result = cursor.fetchone()
                    return result[0] if result else 0
                else:
                    cursor.execute("SELECT SUM(total_requests) FROM SEARCH_HISTORY")
                    result = cursor.fetchone()
                    return result[0] if result[0] is not None else 0
        except Error as e:
            logger.error(f"Erreur lors du chargement des compteurs : {e}")
            st.error("Erreur lors du chargement des compteurs.")
            return 0

    def increment_total_requests(self, user_id, num_requests):
        """Incrémenter le compteur de requêtes pour un utilisateur."""
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE USERS SET total_requests = total_requests + %s WHERE username = %s",
                               (num_requests, user_id))
                conn.commit()
                if cursor.rowcount > 0:
                    logger.info(f"Compteur de requêtes mis à jour : user={user_id}, +{num_requests} requêtes")
                else:
                    logger.warning(f"Utilisateur {user_id} non trouvé pour mise à jour du compteur")
                    st.error("Utilisateur introuvable pour mise à jour du compteur.")
        except Error as e:
            logger.error(f"Erreur lors de la mise à jour du compteur pour {user_id} : {e}")
            st.error("Erreur lors de la mise à jour du compteur.")
            raise

    def load_request_count(self):
        """Charger les compteurs de requêtes pour tous les utilisateurs."""
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT username, total_requests FROM USERS")
                counts = {row[0]: {"total_requests": row[1]} for row in cursor.fetchall()}
                return counts
        except Error as e:
            logger.error(f"Erreur lors du chargement des compteurs : {e}")
            return {}

    def save_request_count(self, counts):
        """Enregistrer les compteurs de requêtes."""
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                for username, data in counts.items():
                    cursor.execute(
                        "UPDATE USERS SET total_requests = %s WHERE username = %s",
                        (data['total_requests'], username)
                    )
                conn.commit()
                logger.info("Compteur de requêtes enregistré")
        except Error as e:
            logger.error(f"Erreur lors de la sauvegarde des compteurs : {e}")
            raise