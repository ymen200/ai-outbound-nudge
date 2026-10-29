import requests
import json
import time
import os
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION UPLEAD ---
UPLEAD_API_KEY = os.getenv("UPLEAD_API_KEY")
if not UPLEAD_API_KEY:
    raise ValueError("UPLEAD_API_KEY manquante dans .env")
TARGET_DOMAIN = "nasa.gov" 
OUTPUT_FILE = "nasa_uplead_results.json"

# Liste des cibles NASA pour le test
TEST_PROFILES = [
    {
        "first_name": "Bill",
        "last_name": "Nelson",
    },
    {
        "first_name": "Casey",
        "last_name": "Swails",
    },
    {
        "first_name": "Vanessa",
        "last_name": "Wyche",
    }
]

def get_headers():
    return {
        "Authorization": UPLEAD_API_KEY,
        "Content-Type": "application/json"
    }

def enrich_person_uplead(first_name, last_name, domain):
    """
    Appel à l'endpoint de recherche de personnes d'UpLead
    """
    api_url = "https://api.uplead.com/v2/person-search"
    params = {
        'first_name': first_name,
        'last_name': last_name,
        'domain': domain
    }
    
    try:
        response = requests.get(api_url, headers=get_headers(), params=params, timeout=20)
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"⚠️ Erreur API ({response.status_code}): {response.text}")
            return None
    except Exception as e:
        print(f"❌ Erreur de connexion : {e}")
        return None

def run_nasa_test():
    final_results = []
    print(f"🚀 Démarrage du test UpLead pour le domaine {TARGET_DOMAIN}...")

    for p in TEST_PROFILES:
        full_name = f"{p['first_name']} {p['last_name']}"
        print(f"\n--- Recherche NASA : {full_name} ---")
        
        data = enrich_person_uplead(p['first_name'], p['last_name'], TARGET_DOMAIN)
        
        # Vérification robuste pour éviter le KeyError: 0
        if data and "data" in data and isinstance(data["data"], list) and len(data["data"]) > 0:
            
            person = data["data"][0] 
            
            email = person.get('email', 'Non trouvé')
            phone = person.get('phone', 'Non trouvé')
            title = person.get('title', 'N/A')
            linkedin = person.get('linkedin_url', 'N/A')

            print(f"✅ Succès ! 📧 {email} | 📞 {phone}")

            final_results.append({
                "searched_name": full_name,
                "actual_name": f"{person.get('first_name', '')} {person.get('last_name', '')}",
                "job_title": title,
                "email": email,
                "phone": phone,
                "linkedin": linkedin,
                "status": "Success"
            })
        else:
            print(f"ℹ️ Aucun résultat trouvé pour {full_name} à la NASA.")
            final_results.append({
                "searched_name": full_name,
                "status": "Not Found",
                "details": "Individu absent de la base de données UpLead pour ce domaine."
            })

        time.sleep(1)

    # Sauvegarde finale
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_results, f, indent=4, ensure_ascii=False)

    print(f"\n✨ Test NASA terminé. Résultats enregistrés dans : {OUTPUT_FILE}")

if __name__ == "__main__":
    run_nasa_test()