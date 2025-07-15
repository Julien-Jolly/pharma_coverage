import bcrypt
import json

# Nouveau mot de passe (à modifier selon vos besoins)
new_password = "A9zg3ofw".encode('utf-8')

# Générer un hash bcrypt
salt = bcrypt.gensalt()
hashed_password = bcrypt.hashpw(new_password, salt)

# Charger le fichier users.json existant
with open("users.json", "r") as f:
    users = json.load(f)

# Mettre à jour le mot de passe admin
users["Administateur"] = {"password": hashed_password.decode('utf-8'), "credits": users["Administateur"]["credits"] if "credits" in users["Administateur"] else 0}

# Sauvegarder les modifications
with open("users.json", "w") as f:
    json.dump(users, f, indent=2)