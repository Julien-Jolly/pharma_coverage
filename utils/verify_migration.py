import sqlite3
import json
import boto3
import logging
import os
import streamlit as st
from typing import Dict, List, Any
from datetime import datetime

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, filename="migration_verification.log",
                    format="%(asctime)s - %(levelname)s - %(message)s")


def download_from_s3(bucket: str, key: str, local_path: str) -> bool:
    """Télécharger un fichier depuis S3."""
    try:
        s3 = boto3.client("s3")
        s3.download_file(bucket, key, local_path)
        logger.info(f"Fichier téléchargé depuis S3 : {key} -> {local_path}")
        return True
    except Exception as e:
        logger.error(f"Erreur lors du téléchargement depuis S3 ({key}) : {e}")
        return False


def upload_to_s3(bucket: str, key: str, local_path: str):
    """Téléverser un fichier vers S3 sans vérification MD5."""
    try:
        s3 = boto3.client("s3")
        with open(local_path, "rb") as f:
            s3.upload_fileobj(f, bucket, key, ExtraArgs={"ContentType": "text/plain; charset=utf-8"})
        logger.info(f"Fichier téléversé vers S3 : {local_path} -> {key}")
    except Exception as e:
        logger.error(f"Erreur lors du téléversement vers S3 ({local_path}) : {e}")
        raise


def load_json_from_s3(bucket: str, key: str) -> Dict[str, Any]:
    """Charger un fichier JSON depuis S3."""
    local_path = os.path.basename(key)
    if download_from_s3(bucket, key, local_path):
        with open(local_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def compare_users(json_data: Dict[str, Any], db_path: str) -> List[str]:
    """Comparer les utilisateurs de users.json avec la table USERS."""
    discrepancies = []
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT username, password, credits, is_admin, total_requests FROM USERS")
        db_users = {row[0]: {"password": row[1], "credits": row[2], "is_admin": row[3], "total_requests": row[4]} for
                    row in cursor.fetchall()}
        conn.close()

        for username, user in json_data.items():
            if username not in db_users:
                discrepancies.append(f"Utilisateur {username} manquant dans la base de données")
            else:
                db_user = db_users[username]
                if user["password"] != db_user["password"]:
                    discrepancies.append(
                        f"Utilisateur {username} : mot de passe différent (JSON: {user['password']}, DB: {db_user['password']})")
                if user.get("credits") != db_user["credits"]:
                    discrepancies.append(
                        f"Utilisateur {username} : crédits différents (JSON: {user.get('credits')}, DB: {db_user['credits']})")
                if user.get("is_admin", False) != db_user["is_admin"]:
                    discrepancies.append(
                        f"Utilisateur {username} : is_admin différent (JSON: {user.get('is_admin', False)}, DB: {db_user['is_admin']})")

        for username in db_users:
            if username not in json_data:
                discrepancies.append(f"Utilisateur {username} présent dans la base mais absent du JSON")

        logger.info(
            f"Vérification des utilisateurs : {len(json_data)} dans JSON, {len(db_users)} dans DB, {len(discrepancies)} différences")
        return discrepancies
    except Exception as e:
        logger.error(f"Erreur lors de la comparaison des utilisateurs : {e}")
        raise


def compare_request_counts(json_data: Dict[str, Any], db_path: str) -> List[str]:
    """Comparer les comptes de requêtes de request_count.json avec la table USERS."""
    discrepancies = []
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT username, total_requests FROM USERS")
        db_requests = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()

        for username, data in json_data.items():
            total_requests = data if isinstance(data, int) else data.get("total_requests", 0)
            if username not in db_requests:
                discrepancies.append(f"Utilisateur {username} manquant dans USERS pour request_count")
            else:
                db_total_requests = db_requests[username]
                if total_requests != db_total_requests:
                    discrepancies.append(
                        f"Utilisateur {username} : total_requests différent (JSON: {total_requests}, DB: {db_total_requests})")

        for username, total_requests in db_requests.items():
            if total_requests != 0 and username not in json_data:
                discrepancies.append(
                    f"Utilisateur {username} : total_requests={total_requests} dans la base mais absent de request_count.json")

        logger.info(
            f"Vérification des comptes de requêtes : {len(json_data)} dans JSON, {len(db_requests)} dans DB, {len(discrepancies)} différences")
        return discrepancies
    except Exception as e:
        logger.error(f"Erreur lors de la comparaison des comptes de requêtes : {e}")
        raise


def compare_searches(json_data: List[Dict[str, Any]], db_path: str) -> List[str]:
    """Comparer les recherches de search_history.json avec SEARCH_HISTORY et les tables associées."""
    discrepancies = []
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM SEARCH_HISTORY")
        columns = [desc[0] for desc in cursor.description]
        db_searches = []
        for row in cursor.fetchall():
            entry = dict(zip(columns, row))
            entry["bounds"] = json.loads(entry["bounds"])
            cursor.execute("""
            SELECT p.name, p.latitude, p.longitude
            FROM PHARMACIES p
            JOIN SEARCH_PHARMACIES sp ON p.id = sp.pharmacy_id
            WHERE sp.search_id = ?
            """, (entry["id"],))
            entry["pharmacies"] = [{"name": r[0], "latitude": r[1], "longitude": r[2]} for r in cursor.fetchall()]
            db_searches.append(entry)

        db_search_index = {(s["name"], s["user_id"]): s for s in db_searches}

        for json_search in json_data:
            key = (json_search["name"], json_search["user_id"])
            if key not in db_search_index:
                discrepancies.append(
                    f"Recherche {json_search['name']} (user_id={json_search['user_id']}) manquante dans la base")
                continue

            db_search = db_search_index[key]
            fields = ["bounds", "search_type", "subarea_step", "subarea_radius", "total_requests",
                      "center_lat", "center_lon", "zoom", "timestamp"]
            for field in fields:
                json_value = json_search.get(field)
                db_value = db_search.get(field)
                if field == "bounds" and json_value is not None and db_value is not None:
                    json_value = [round(float(x), 6) for x in json_value] if isinstance(json_value,
                                                                                        list) else json_value
                    db_value = [round(float(x), 6) for x in db_value] if isinstance(db_value, list) else db_value
                if field == "timestamp":
                    continue  # Ignorer les différences de timestamp
                if json_value != db_value:
                    discrepancies.append(
                        f"Recherche {json_search['name']} (user_id={json_search['user_id']}) : champ {field} différent (JSON: {json_value}, DB: {db_value})")

            json_pharmacies = sorted(json_search.get("pharmacies", []),
                                     key=lambda x: (x["name"], x["latitude"], x["longitude"]))
            db_pharmacies = sorted(db_search.get("pharmacies", []),
                                   key=lambda x: (x["name"], x["latitude"], x["longitude"]))
            if len(json_pharmacies) != len(db_pharmacies):
                discrepancies.append(
                    f"Recherche {json_search['name']} (user_id={json_search['user_id']}) : nombre de pharmacies différent (JSON: {len(json_pharmacies)}, DB: {len(db_pharmacies)})")
            else:
                for jp, dp in zip(json_pharmacies, db_pharmacies):
                    jp_rounded = {"name": jp["name"], "latitude": round(float(jp["latitude"]), 6),
                                  "longitude": round(float(jp["longitude"]), 6)}
                    dp_rounded = {"name": dp["name"], "latitude": round(float(dp["latitude"]), 6),
                                  "longitude": round(float(dp["longitude"]), 6)}
                    if jp_rounded != dp_rounded:
                        discrepancies.append(
                            f"Recherche {json_search['name']} (user_id={json_search['user_id']}) : pharmacie différente (JSON: {jp_rounded}, DB: {dp_rounded})")

        for key in db_search_index:
            if key not in [(s["name"], s["user_id"]) for s in json_data]:
                discrepancies.append(
                    f"Recherche {key[0]} (user_id={key[1]}) présente dans la base mais absente du JSON")

        cursor.execute("SELECT id, name, latitude, longitude FROM PHARMACIES")
        db_pharmacies = [{"id": row[0], "name": row[1], "latitude": row[2], "longitude": row[3]} for row in
                         cursor.fetchall()]
        cursor.execute("SELECT DISTINCT pharmacy_id FROM SEARCH_PHARMACIES")
        linked_pharmacy_ids = set(row[0] for row in cursor.fetchall())
        for pharmacy in db_pharmacies:
            if pharmacy["id"] not in linked_pharmacy_ids:
                discrepancies.append(f"Pharmacie {pharmacy['name']} (id={pharmacy['id']}) orpheline dans PHARMACIES")

        cursor.execute("SELECT DISTINCT user_id FROM SEARCH_HISTORY")
        search_user_ids = set(row[0] for row in cursor.fetchall())
        cursor.execute("SELECT username FROM USERS")
        user_ids = set(row[0] for row in cursor.fetchall())
        for user_id in search_user_ids:
            if user_id not in user_ids:
                discrepancies.append(f"Recherche avec user_id={user_id} sans utilisateur correspondant dans USERS")

        conn.close()
        logger.info(
            f"Vérification des recherches : {len(json_data)} dans JSON, {len(db_searches)} dans DB, {len(discrepancies)} différences")
        return discrepancies
    except Exception as e:
        logger.error(f"Erreur lors de la comparaison des recherches : {e}")
        raise


def verify_migration(
        bucket: str = None,
        users_json_s3_key: str = "users.json",
        search_json_s3_key: str = "search_history.json",
        request_count_s3_key: str = "request_count.json",
        db_key: str = "database.db",
        db_path: str = "database.db",
        report_path: str = "migration_report.txt",
        report_s3_key: str = "migration_report.txt"
):
    """Vérifier que toutes les données JSON ont été correctement migrées vers SQLite."""
    discrepancies = []
    bucket = bucket or st.secrets["S3_BUCKET_NAME"]

    if not download_from_s3(bucket, db_key, db_path):
        logger.error("Impossible de télécharger la base de données depuis S3")
        return ["Erreur : impossible de télécharger la base de données depuis S3"]

    users_json = load_json_from_s3(bucket, users_json_s3_key)
    if users_json:
        discrepancies.extend(compare_users(users_json, db_path))
    else:
        discrepancies.append(f"Erreur : impossible de charger {users_json_s3_key} depuis S3")

    request_json = load_json_from_s3(bucket, request_count_s3_key)
    if request_json:
        discrepancies.extend(compare_request_counts(request_json, db_path))
    else:
        logger.info(f"Fichier {request_count_s3_key} non trouvé ou inaccessible, saut de la vérification des requêtes")

    search_json = load_json_from_s3(bucket, search_json_s3_key)
    if search_json:
        discrepancies.extend(compare_searches(search_json, db_path))
    else:
        discrepancies.append(f"Erreur : impossible de charger {search_json_s3_key} depuis S3")

    report = f"Rapport de vérification de la migration - {datetime.now().isoformat()}\n\n"
    if not discrepancies:
        report += "Aucune différence détectée. Toutes les données JSON ont été correctement migrées.\n"
    else:
        report += f"{len(discrepancies)} différences détectées :\n"
        for i, discrepancy in enumerate(discrepancies, 1):
            report += f"{i}. {discrepancy}\n"

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info(f"Rapport généré : {report_path}")

    upload_to_s3(bucket, report_s3_key, report_path)

    return discrepancies


if __name__ == "__main__":
    discrepancies = verify_migration()
    if discrepancies:
        logger.error(
            f"Vérification de la migration échouée : {len(discrepancies)} différences. Consultez s3://jujul/migration_report.txt")
        print(
            f"Échec de la vérification : {len(discrepancies)} différences trouvées. Consultez migration_report.txt sur S3.")
    else:
        logger.info("Vérification réussie : toutes les données ont été correctement migrées.")
        print("Vérification réussie : toutes les données ont été correctement migrées.")