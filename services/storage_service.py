import streamlit as st
import boto3
import json
import logging

logger = logging.getLogger(__name__)

class StorageService:
    """Service pour gérer le stockage des données dans AWS S3."""

    def __init__(self):
        """Initialiser le client S3."""
        try:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=st.secrets["AWS_ACCESS_KEY_ID"],
                aws_secret_access_key=st.secrets["AWS_SECRET_ACCESS_KEY"],
                region_name=st.secrets["AWS_REGION"]
            )
            self.bucket_name = st.secrets["S3_BUCKET_NAME"]
            logger.info(f"Client S3 initialisé pour le bucket {self.bucket_name}")
        except Exception as e:
            st.error(f"Erreur lors de l'initialisation du client S3 : {e}")
            logger.error(f"Erreur lors de l'initialisation du client S3 : {e}")
            raise

    def load_search_history(self):
        """Charger l'historique des recherches depuis S3."""
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key="search_history.json")
            history = json.loads(response['Body'].read().decode('utf-8'))
            logger.info(f"Historique chargé : {len(history)} recherches")
            return history
        except self.s3_client.exceptions.NoSuchKey:
            logger.info("Fichier search_history.json non trouvé dans S3, retour d'une liste vide")
            return []
        except Exception as e:
            st.error(f"Erreur lors du chargement de l'historique : {e}")
            logger.error(f"Erreur lors du chargement de l'historique : {e}")
            return []

    def save_search_history(self, search_data):
        """Enregistrer une recherche dans l'historique sur S3."""
        try:
            history = self.load_search_history()
            history.append(search_data)
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key="search_history.json",
                Body=json.dumps(history, indent=2).encode('utf-8')
            )
            logger.info(f"Recherche enregistrée : {search_data['name']}")
        except Exception as e:
            st.error(f"Erreur lors de l'enregistrement de l'historique : {e}")
            logger.error(f"Erreur lors de l'enregistrement de l'historique : {e}")

    def get_total_requests(self):
        """Obtenir le compteur global de requêtes depuis S3."""
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key="request_count.json")
            data = json.loads(response['Body'].read().decode('utf-8'))
            total_requests = data.get("total_requests", 0)
            logger.info(f"Compteur de requêtes chargé : {total_requests}")
            return total_requests
        except self.s3_client.exceptions.NoSuchKey:
            logger.info("Fichier request_count.json non trouvé dans S3, retour 0")
            return 0
        except Exception as e:
            st.error(f"Erreur lors de la lecture du compteur de requêtes : {e}")
            logger.error(f"Erreur lors de la lecture du compteur de requêtes : {e}")
            return 0

    def update_request_count(self, requests):
        """Mettre à jour le compteur de requêtes dans S3."""
        try:
            total_requests = self.get_total_requests() + requests
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key="request_count.json",
                Body=json.dumps({"total_requests": total_requests}, indent=2).encode('utf-8')
            )
            logger.info(f"Compteur de requêtes mis à jour : {total_requests} requêtes")
            return total_requests
        except Exception as e:
            st.error(f"Erreur lors de la mise à jour du compteur de requêtes : {e}")
            logger.error(f"Erreur lors de la mise à jour du compteur de requêtes : {e}")
            return requests

    def is_search_name_unique(self, name):
        """Vérifier si un nom de recherche est unique."""
        history = self.load_search_history()
        return not any(search["name"] == name for search in history)