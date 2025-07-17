import json
from services.storage_service import StorageService
from utils.helpers import generate_pharmacies_key

def generate_subzone_key(lat, lon, radius):
    return f"{round(lat, 5)}_{round(lon, 5)}_{radius}"

def initialize_subzones():
    storage = StorageService()
    subzones_key = "subzones.json"

    # Charger l'existant
    try:
        response = storage.s3_client.get_object(Bucket=storage.bucket_name, Key=subzones_key)
        subzones = json.loads(response['Body'].read().decode('utf-8'))
    except Exception:
        subzones = {}

    # Charger l’historique existant
    history = storage.load_search_history()

    # Nouveau format d’historique
    new_history = []

    for entry in history:
        if 'pharmacies' in entry:
            subzones_used = []
            for pharmacy in entry['pharmacies']:
                lat, lon = pharmacy['latitude'], pharmacy['longitude']
                radius = entry.get('subarea_radius', 1000)  # fallback
                key = generate_subzone_key(lat, lon, radius)

                if key not in subzones:
                    subzones[key] = []
                if pharmacy not in subzones[key]:
                    subzones[key].append(pharmacy)
                subzones_used.append(key)

            # Nettoyage de l’entrée
            entry.pop("pharmacies", None)
            entry["subzones_used"] = list(set(subzones_used))

        new_history.append(entry)

    # Sauvegarde
    storage.s3_client.put_object(
        Bucket=storage.bucket_name,
        Key="subzones.json",
        Body=json.dumps(subzones, indent=2).encode('utf-8')
    )
    print("✅ subzones.json mis à jour avec toutes les pharmacies groupées par sous-zone.")

    storage.save_search_history(new_history, overwrite=True)
    print("✅ search_history.json restructuré pour référencer les sous-zones.")

if __name__ == "__main__":
    initialize_subzones()
