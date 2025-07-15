import mysql.connector
from mysql.connector import Error
import json
import logging
import boto3
import streamlit as st
from datetime import datetime
import os

logger = logging.getLogger(__name__)

def init_db(db_config):
    """Initialiser la base de données avec les tables nécessaires."""
    try:
        # Connecter sans spécifier de base pour vérifier/créer la base pharmacy_db
        conn = mysql.connector.connect(
            host=db_config['host'],
            port=db_config['port'],
            user=db_config['user'],
            password=db_config['password']
        )
        cursor = conn.cursor()
        cursor.execute("CREATE DATABASE IF NOT EXISTS pharmacy_db")
        cursor.close()
        conn.close()

        # Reconnecter avec la base pharmacy_db
        conn = mysql.connector.connect(
            host=db_config['host'],
            port=db_config['port'],
            database=db_config['database'],
            user=db_config['user'],
            password=db_config['password']
        )
        cursor = conn.cursor()

        # Créer la table USERS
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS USERS (
                username VARCHAR(255) PRIMARY KEY,
                password VARCHAR(255) NOT NULL,
                credits INT DEFAULT 0,
                is_admin BOOLEAN DEFAULT FALSE,
                total_requests INT DEFAULT 0
            )
        """)

        # Créer la table PHARMACIES
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS PHARMACIES (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                address TEXT,
                latitude DECIMAL(9,6),
                longitude DECIMAL(9,6),
                UNIQUE KEY unique_pharmacy (name, latitude, longitude)
            )
        """)

        # Créer la table SEARCH_HISTORY
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS SEARCH_HISTORY (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                user_id VARCHAR(255) NOT NULL,
                bounds JSON,
                search_type VARCHAR(50),
                subarea_step DECIMAL(9,6),
                subarea_radius INT,
                total_requests INT,
                map_html TEXT,
                center_lat DECIMAL(9,6),
                center_lon DECIMAL(9,6),
                zoom INT,
                timestamp DATETIME,
                FOREIGN KEY (user_id) REFERENCES USERS(username)
            )
        """)

        # Créer la table SEARCH_PHARMACIES
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS SEARCH_PHARMACIES (
                search_id BIGINT,
                pharmacy_id BIGINT,
                PRIMARY KEY (search_id, pharmacy_id),
                FOREIGN KEY (search_id) REFERENCES SEARCH_HISTORY(id),
                FOREIGN KEY (pharmacy_id) REFERENCES PHARMACIES(id)
            )
        """)

        # Créer la table ACTIVE_IPS
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ACTIVE_IPS (
                ip_address VARCHAR(45) PRIMARY KEY,
                added_at DATETIME NOT NULL,
                expires_at DATETIME NOT NULL
            )
        """)

        # Créer la table MIGRATION_STATUS
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS MIGRATION_STATUS (
                id INT PRIMARY KEY,
                status VARCHAR(50) NOT NULL,
                last_migration_date DATETIME
            )
        """)
        # Insérer un enregistrement initial si la table est vide
        cursor.execute("INSERT IGNORE INTO MIGRATION_STATUS (id, status, last_migration_date) VALUES (1, 'pending', NULL)")

        conn.commit()
        logger.info(
            "Base de données initialisée avec succès : tables USERS, PHARMACIES, SEARCH_HISTORY, SEARCH_PHARMACIES, ACTIVE_IPS, MIGRATION_STATUS créées si nécessaire.")
    except Error as e:
        logger.error(f"Erreur lors de l'initialisation de la base de données : {e}")
        raise
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals() and conn.is_connected():
            conn.close()
            logger.info("Connexion à la base de données fermée.")

def download_from_s3(bucket, key, local_path):
    """Télécharger un fichier depuis S3."""
    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=st.secrets.get('AWS_ACCESS_KEY_ID', os.getenv('AWS_ACCESS_KEY_ID', '')),
            aws_secret_access_key=st.secrets.get('AWS_SECRET_ACCESS_KEY', os.getenv('AWS_SECRET_ACCESS_KEY', '')),
            region_name=st.secrets.get('AWS_REGION', os.getenv('AWS_REGION', 'eu-north-1'))
        )
        s3.download_file(bucket, key, local_path)
        logger.info(f"Fichier téléchargé depuis S3 : {key} -> {local_path}")
    except Exception as e:
        logger.error(f"Erreur lors du téléchargement depuis S3 ({key}) : {e}")
        raise

def upload_to_s3(bucket, key, local_path):
    """Téléverser un fichier vers S3."""
    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=st.secrets.get('AWS_ACCESS_KEY_ID', os.getenv('AWS_ACCESS_KEY_ID', '')),
            aws_secret_access_key=st.secrets.get('AWS_SECRET_ACCESS_KEY', os.getenv('AWS_SECRET_ACCESS_KEY', '')),
            region_name=st.secrets.get('AWS_REGION', os.getenv('AWS_REGION', 'eu-north-1'))
        )
        s3.upload_file(local_path, bucket, key)
        logger.info(f"Fichier téléversé vers S3 : {local_path} -> {key}")
    except Exception as e:
        logger.error(f"Erreur lors du téléversement vers S3 ({local_path}) : {e}")
        raise

def migrate_json_to_mysql(db_config, search_json_s3_key="search_history.json", users_json_s3_key="users.json", request_count_s3_key="request_count.json"):
    """Migrer les données JSON depuis S3 vers MySQL."""
    conn = None
    try:
        bucket = st.secrets.get("S3_BUCKET_NAME", '')
        if not bucket:
            raise ValueError("S3_BUCKET_NAME non défini dans st.secrets")

        # Vérifier si la migration a déjà eu lieu
        conn = mysql.connector.connect(
            host=db_config['host'],
            port=db_config['port'],
            database=db_config['database'],
            user=db_config['user'],
            password=db_config['password']
        )
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM MIGRATION_STATUS WHERE id = 1")
        result = cursor.fetchone()
        if result and result[0] == "completed":
            logger.info("Migration déjà effectuée, saut de la migration.")
            return

        # Télécharger et migrer les fichiers
        download_from_s3(bucket, users_json_s3_key, "users.json")
        download_from_s3(bucket, search_json_s3_key, "search_history.json")
        try:
            download_from_s3(bucket, request_count_s3_key, "request_count.json")
        except Exception as e:
            logger.warning(f"Fichier request_count.json non trouvé ou inaccessible : {e}. Poursuite sans ce fichier.")

        # Migrer users.json
        with open("users.json", "r") as f:
            users_data = json.load(f)
        for username, user in users_data.items():
            cursor.execute(
                "INSERT IGNORE INTO USERS (username, password, credits, is_admin, total_requests) VALUES (%s, %s, %s, %s, %s)",
                (username, user["password"], user.get("credits", 0), user.get("is_admin", False), 0)
            )
        logger.info(f"Migration réussie : {len(users_data)} utilisateurs migrés")

        # Migrer request_count.json (si disponible)
        try:
            with open("request_count.json", "r") as f:
                request_data = json.load(f)
            updated_count = 0
            for username, data in request_data.items():
                if username != "admin" and isinstance(data, dict) and "total_requests" in data:
                    total_requests = data["total_requests"]
                    cursor.execute(
                        "SELECT username FROM USERS WHERE username = %s",
                        (username,)
                    )
                    if cursor.fetchone():
                        cursor.execute(
                            "UPDATE USERS SET total_requests = %s WHERE username = %s",
                            (total_requests, username)
                        )
                        updated_count += 1
                    else:
                        logger.warning(f"Utilisateur {username} non trouvé dans USERS, mise à jour ignorée")
            logger.info(f"Migration réussie : {updated_count} comptes de requêtes mis à jour (admin exclu)")
        except FileNotFoundError:
            logger.info("Aucun fichier request_count.json trouvé localement, saut de la migration des requêtes")
        except Exception as e:
            logger.warning(f"Erreur lors de la migration de request_count.json : {e}. Poursuite sans ce fichier.")

        # Migrer search_history.json
        with open("search_history.json", "r") as f:
            search_data = json.load(f)
        for entry in search_data:
            user_id = entry.get("user_id", "unknown")
            if user_id == "unknown":
                logger.warning(f"Entrée {entry['name']} n'a pas de user_id, valeur par défaut 'unknown' utilisée")
            cursor.execute(
                "INSERT IGNORE INTO SEARCH_HISTORY (name, user_id, bounds, search_type, subarea_step, subarea_radius, total_requests, map_html, center_lat, center_lon, zoom, timestamp) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    entry["name"],
                    user_id,
                    json.dumps(entry["bounds"]),
                    entry["search_type"],
                    entry["subarea_step"],
                    entry["subarea_radius"],
                    entry["total_requests"],
                    entry["map_html"],
                    entry["center_lat"],
                    entry["center_lon"],
                    entry["zoom"],
                    entry.get("timestamp", datetime.now().isoformat())
                )
            )
            search_id = cursor.lastrowid

            # Grouper les insertions de pharmacies
            pharmacy_values = []
            existing_pharmacies = set()
            cursor.execute("SELECT name, latitude, longitude FROM PHARMACIES")
            for row in cursor.fetchall():
                existing_pharmacies.add((row[0], row[1], row[2]))
            for pharmacy in entry.get("pharmacies", []):
                pharmacy_key = (pharmacy["name"], pharmacy["latitude"], pharmacy["longitude"])
                if pharmacy_key not in existing_pharmacies:
                    pharmacy_values.append((
                        pharmacy["name"],
                        pharmacy.get("address"),
                        pharmacy["latitude"],
                        pharmacy["longitude"]
                    ))
                    existing_pharmacies.add(pharmacy_key)

            if pharmacy_values:
                cursor.executemany(
                    "INSERT IGNORE INTO PHARMACIES (name, address, latitude, longitude) VALUES (%s, %s, %s, %s)",
                    pharmacy_values
                )
                logger.info(f"Insertion de {len(pharmacy_values)} pharmacies pour la recherche {entry['name']}")
            else:
                logger.info(f"Aucune nouvelle pharmacie à insérer pour la recherche {entry['name']}")

            # Lier les pharmacies à la recherche
            if pharmacy_values:
                placeholders = ','.join(['(%s, %s, %s)'] * len(pharmacy_values))
                query = f"SELECT id FROM PHARMACIES WHERE (name, latitude, longitude) IN ({placeholders})"
                cursor.execute(query, [item for sublist in pharmacy_values for item in sublist[:3]])
                pharmacy_ids = {row[0] for row in cursor.fetchall()}
                for pharmacy in entry.get("pharmacies", []):
                    cursor.execute(
                        "SELECT id FROM PHARMACIES WHERE name = %s AND latitude = %s AND longitude = %s",
                        (pharmacy["name"], pharmacy["latitude"], pharmacy["longitude"])
                    )
                    result = cursor.fetchone()
                    if result:
                        pharmacy_id = result[0]
                        if pharmacy_id in pharmacy_ids:
                            cursor.execute(
                                "INSERT IGNORE INTO SEARCH_PHARMACIES (search_id, pharmacy_id) VALUES (%s, %s)",
                                (search_id, pharmacy_id)
                            )

        # Marquer la migration comme terminée
        cursor.execute("UPDATE MIGRATION_STATUS SET last_migration_date = NOW(), status = 'completed' WHERE id = 1")
        conn.commit()
        logger.info(f"Migration réussie : {len(search_data)} recherches migrées")
    except Error as e:
        logger.error(f"Erreur lors de la migration : {e}")
        raise
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals() and conn.is_connected():
            conn.close()
            logger.info("Connexion à la base de données fermée.")