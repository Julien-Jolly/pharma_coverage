import json
import hashlib
import boto3
import streamlit as st
from botocore.exceptions import ClientError

# Chargement des secrets Streamlit
AWS_ACCESS_KEY_ID = st.secrets["AWS_ACCESS_KEY_ID"]
AWS_SECRET_ACCESS_KEY = st.secrets["AWS_SECRET_ACCESS_KEY"]
AWS_REGION = st.secrets["AWS_REGION"]
BUCKET_NAME = st.secrets["S3_BUCKET_NAME"]

# Clés des fichiers dans S3
HISTORY_KEY = "search_history.json"
PHARMACY_KEY = "pharmacies.json"

# Client S3 authentifié
s3_client = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION
)

def generate_pharmacy_id(pharmacy):
    raw = f"{pharmacy['name'].strip().lower()}_{pharmacy['latitude']}_{pharmacy['longitude']}"
    return hashlib.md5(raw.encode()).hexdigest()

def load_json_from_s3(key):
    try:
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key=key)
        content = response["Body"].read().decode("utf-8")
        return json.loads(content)
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return []
        else:
            raise e

def write_json_to_s3(key, data):
    try:
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        )
        print(f"✅ Fichier {key} mis à jour sur S3.")
    except ClientError as e:
        print(f"❌ Erreur S3 lors de l’écriture de {key} : {e}")

def migrate():
    print("📥 Lecture de l'historique depuis S3...")
    history = load_json_from_s3(HISTORY_KEY)
    all_pharmacies = {}
    new_history = []

    for search in history:
        pharmacies = search.get("pharmacies", [])
        pharmacy_ids = []
        for pharmacy in pharmacies:
            pid = generate_pharmacy_id(pharmacy)
            pharmacy_ids.append(pid)
            if pid not in all_pharmacies:
                all_pharmacies[pid] = {
                    "id": pid,
                    "name": pharmacy["name"],
                    "latitude": pharmacy["latitude"],
                    "longitude": pharmacy["longitude"]
                }

        search["pharmacy_ids"] = pharmacy_ids
        search.pop("pharmacies", None)
        new_history.append(search)

    print(f"🧠 {len(all_pharmacies)} pharmacies uniques identifiées")
    write_json_to_s3(PHARMACY_KEY, {"pharmacies": all_pharmacies})
    write_json_to_s3(HISTORY_KEY, new_history)

    print("✅ Migration terminée avec succès.")

if __name__ == "__main__":
    migrate()
