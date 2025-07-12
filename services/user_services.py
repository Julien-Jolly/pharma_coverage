import bcrypt
import streamlit as st
from .storage_service import StorageService
import logging

logger = logging.getLogger(__name__)

class UserService:
    def __init__(self, storage_service):
        self.storage = storage_service
        self.admin_password = st.secrets["ADMIN_PASSWORD"].encode('utf-8')

    def authenticate_user(self, username, password):
        """Authentifie un utilisateur standard."""
        try:
            users = self.storage.load_users()
            user_data = users.get(username)
            if user_data and bcrypt.checkpw(password.encode('utf-8'), user_data['password'].encode('utf-8')):
                logger.info(f"Authentification réussie pour l'utilisateur {username}")
                return True
            logger.warning(f"Échec de l'authentification pour l'utilisateur {username}")
            return False
        except Exception as e:
            logger.error(f"Erreur lors de l'authentification utilisateur : {e}")
            st.error("Erreur lors de l'authentification.")
            return False

    def authenticate_admin(self, password):
        """Authentifie l'administrateur."""
        try:
            if bcrypt.checkpw(password.encode('utf-8'), self.admin_password):
                logger.info("Authentification admin réussie")
                return True
            logger.warning("Échec de l'authentification admin")
            return False
        except Exception as e:
            logger.error(f"Erreur lors de l'authentification admin : {e}")
            st.error("Erreur lors de l'authentification admin.")
            return False

    def get_user_credits(self, username):
        """Récupère les crédits d'un utilisateur."""
        try:
            users = self.storage.load_users()
            if username in users:
                return users[username]['credits']
            logger.warning(f"Utilisateur {username} non trouvé pour récupérer les crédits")
            return None
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des crédits pour {username} : {e}")
            st.error("Erreur lors de la récupération des crédits.")
            return None

    def update_credits(self, username, credits):
        """Met à jour les crédits d'un utilisateur."""
        try:
            users = self.storage.load_users()
            if username not in users:
                logger.warning(f"Tentative de mise à jour des crédits pour un utilisateur inexistant : {username}")
                st.error("Utilisateur introuvable.")
                return False
            users[username]['credits'] = credits
            self.storage.save_users(users)
            logger.info(f"Crédits mis à jour pour {username} : {credits} crédits")
            return True
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour des crédits pour {username} : {e}")
            st.error("Erreur lors de la mise à jour des crédits.")
            return False

    def create_user(self, username, password, initial_credits=10):
        """Crée un nouvel utilisateur avec des crédits initiaux."""
        try:
            users = self.storage.load_users()
            if username in users or username == "admin":
                logger.warning(f"Tentative d'inscription avec un nom d'utilisateur existant : {username}")
                st.error("Ce nom d'utilisateur existe déjà.")
                return False
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            users[username] = {"password": hashed_password, "credits": initial_credits}
            self.storage.save_users(users)
            logger.info(f"Utilisateur {username} créé avec {initial_credits} crédits")
            return True
        except Exception as e:
            logger.error(f"Erreur lors de la création de l'utilisateur {username} : {e}")
            st.error("Erreur lors de la création de l'utilisateur.")
            return False

    def delete_user(self, username):
        """Supprime un utilisateur."""
        try:
            users = self.storage.load_users()
            if username not in users:
                logger.warning(f"Tentative de suppression d'un utilisateur inexistant : {username}")
                st.error("Utilisateur introuvable.")
                return False
            del users[username]
            self.storage.save_users(users)
            # Supprimer l'historique et les compteurs de l'utilisateur
            history = self.storage.load_search_history()
            history = [entry for entry in history if entry['user_id'] != username]
            self.storage.save_search_history(history, overwrite=True)
            counts = self.storage.load_request_count()
            if username in counts:
                del counts[username]
                self.storage.save_request_count(counts)
            logger.info(f"Utilisateur {username} supprimé avec succès")
            return True
        except Exception as e:
            logger.error(f"Erreur lors de la suppression de l'utilisateur {username} : {e}")
            st.error("Erreur lors de la suppression de l'utilisateur.")
            return False

    def get_all_users(self):
        """Récupère tous les utilisateurs."""
        try:
            users = self.storage.load_users()
            logger.info(f"Récupération de {len(users)} utilisateurs")
            return users
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des utilisateurs : {e}")
            st.error("Erreur lors de la récupération des utilisateurs.")
            return {}