import boto3
from botocore.exceptions import ClientError
import streamlit as st
import json
import logging
import time

logger = logging.getLogger(__name__)

class StorageService:
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=st.secrets["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=st.secrets["AWS_SECRET_ACCESS_KEY"],
            region_name=st.secrets["AWS_REGION"]
        )
        self.bucket_name = st.secrets["S3_BUCKET_NAME"]
        logger.info("Connexion S3 initialisée")

    def load_users(self):
        """Charge users.json depuis S3."""
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key="users.json")
            users = json.loads(response['Body'].read().decode('utf-8'))
            logger.info(f"Utilisateurs chargés : {len(users)} utilisateurs")
            return users
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.warning("Fichier users.json introuvable, création d'un fichier vide")
                return {}
            logger.error(f"Erreur lors du chargement des utilisateurs : {e}")
            st.error("Erreur lors du chargement des utilisateurs.")
            return {}

    def save_users(self, users):
        """Enregistre users.json dans S3 avec gestion des conflits."""
        for attempt in range(3):
            try:
                self.s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key="users.json",
                    Body=json.dumps(users, indent=2).encode('utf-8')
                )
                logger.info("Utilisateurs enregistrés dans users.json")
                return
            except ClientError as e:
                logger.warning(f"Échec de l'enregistrement (tentative {attempt+1}) : {e}")
                time.sleep(0.5)
        st.error("Impossible de sauvegarder les utilisateurs : conflit d'accès.")
        logger.error("Échec définitif de l'enregistrement des utilisateurs")
        raise Exception("Failed to save users after retries")

    def load_search_history(self, user_id=None):
        """Charge search_history.json depuis S3, filtré par user_id si spécifié."""
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key="search_history.json")
            history = json.loads(response['Body'].read().decode('utf-8'))
            if user_id:
                filtered_history = []
                for entry in history:
                    entry_user_id = entry.get('user_id')
                    if entry_user_id == user_id or (user_id == "admin" and entry_user_id is None):
                        filtered_history.append(entry)
                history = filtered_history
            logger.info(f"Historique chargé : {len(history)} recherches" + (
                f" pour l'utilisateur {user_id}" if user_id else ""))
            return history
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.warning("Fichier search_history.json introuvable, création d'un fichier vide")
                return []
            logger.error(f"Erreur lors du chargement de l'historique : {e}")
            st.error("Erreur lors du chargement de l'historique.")
            return []

    def save_search_history(self, search_data, overwrite=False):
        """Sauvegarde les données de recherche dans search_history.json sur S3."""
        try:
            if overwrite:
                history = search_data  # C’est déjà une liste
            else:
                from datetime import datetime
                search_data['timestamp'] = datetime.utcnow().isoformat()
                history = self.load_search_history()
                history.append(search_data)
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key="search_history.json",
                Body=json.dumps(history, indent=2).encode('utf-8')
            )
            logger.info("Historique de recherche sauvegardé")
        except ClientError as e:
            logger.error(f"Erreur lors de la sauvegarde de l'historique : {e}")
            st.error("Erreur lors de la sauvegarde de l'historique.")

    def is_search_name_unique(self, search_name, user_id=None):
        """Vérifie si le nom de recherche est unique pour un utilisateur ou globalement."""
        history = self.load_search_history(user_id)
        return not any(entry['name'] == search_name for entry in history)

    def get_total_requests(self, user_id=None):
        """Récupère le nombre total de requêtes pour un utilisateur ou globalement."""
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key="request_count.json")
            counts = json.loads(response['Body'].read().decode('utf-8'))
            if user_id:
                data = counts.get(user_id, {})
                return data.get('total_requests', 0) if isinstance(data, dict) else data
            total = 0
            for data in counts.values():
                if isinstance(data, dict):
                    total += data.get('total_requests', 0)
                else:
                    total += data  # Gérer les anciens formats où data est un entier
            return total
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.warning("Fichier request_count.json introuvable, création d'un fichier vide")
                return 0
            logger.error(f"Erreur lors du chargement des compteurs : {e}")
            st.error("Erreur lors du chargement des compteurs.")
            return 0

    def increment_total_requests(self, user_id, num_requests):
        """Incrément le compteur de requêtes pour un utilisateur."""
        for attempt in range(3):
            try:
                counts = self.load_request_count()
                if user_id in counts and isinstance(counts[user_id], int):
                    counts[user_id] = {'total_requests': counts[user_id]}
                counts[user_id] = counts.get(user_id, {'total_requests': 0})
                counts[user_id]['total_requests'] += num_requests
                self.save_request_count(counts)
                logger.info(f"Compteur de requêtes mis à jour : user={user_id}, +{num_requests} requêtes")
                return
            except ClientError as e:
                logger.warning(f"Échec de l'enregistrement (tentative {attempt+1}) : {e}")
                time.sleep(0.5)
        st.error("Impossible de mettre à jour le compteur : conflit d'accès.")
        logger.error("Échec définitif de l'enregistrement du compteur")
        raise Exception("Failed to update request count after retries")

    def load_request_count(self):
        """Charge request_count.json depuis S3."""
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key="request_count.json")
            return json.loads(response['Body'].read().decode('utf-8'))
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.warning("Fichier request_count.json introuvable, création d'un fichier vide")
                return {}
            raise

    def save_request_count(self, counts):
        """Enregistre request_count.json dans S3."""
        for attempt in range(3):
            try:
                self.s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key="request_count.json",
                    Body=json.dumps(counts, indent=2).encode('utf-8')
                )
                logger.info("Compteur de requêtes enregistré")
                return
            except ClientError as e:
                logger.warning(f"Échec de l'enregistrement (tentative {attempt+1}) : {e}")
                time.sleep(0.5)
        raise Exception("Failed to save request count after retries")