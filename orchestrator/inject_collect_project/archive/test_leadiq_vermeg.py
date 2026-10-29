import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
LEADIQ_API_KEY = os.getenv("LEADIQ_API_KEY")
if not LEADIQ_API_KEY:
    raise ValueError("LEADIQ_API_KEY manquante dans .env")
COMPANY_DOMAIN = "vermeg.com"
OUTPUT_FILE = "vermeg_leadiq_final.json"

def fetch_leadiq_personas():
    # V16 : On teste deux formats d'auth radicalement différents
    # 1. API Key directe sans 'Bearer'
    # 2. Ajout du header 'apikey' souvent utilisé par les passerelles Kong/Apollo
    headers = {
        "Authorization": LEADIQ_API_KEY,  # Sans 'Bearer' cette fois
        "apikey": LEADIQ_API_KEY,         # Header alternatif
        "Content-Type": "application/json",
    }

    # On change légèrement l'URL pour pointer vers l'endpoint racine au cas où
    search_url = "https://api.leadiq.com/v1/search/people"

    query = """
    query SearchPeople($input: SearchPeopleInput!) {
      searchPeople(input: $input) {
        results {
          name { first last }
          location { city country }
          currentPositions {
            title
            companyInfo { name }
          }
        }
      }
    }
    """

    variables = {
        "input": {
            "company": { "domain": COMPANY_DOMAIN }
        }
    }

    print(f"📡 Tentative V16 (Auth Directe) pour {COMPANY_DOMAIN}...")
    
    try:
        payload = {"query": query, "variables": variables}
        response = requests.post(search_url, json=payload, headers=headers)

        # Si toujours 401, on tente une dernière chance avec le format 'Basic'
        if response.status_code == 401:
            print("🔄 Échec Auth Directe, tentative via Basic Auth...")
            response = requests.post(search_url, json=payload, auth=(LEADIQ_API_KEY, ""))

        if response.status_code == 200:
            data = response.json()
            if "errors" in data:
                # Si l'erreur est "401: Unauthorized" à l'intérieur du JSON
                print(f"❌ Le serveur GraphQL refuse toujours l'accès : {data['errors'][0]['message']}")
                print("\n🚨 DIAGNOSTIC FINAL :")
                print("Il est fort probable que l'accès API soit bloqué pour les comptes 'Free', même si la clé est générable.")
                print("Vérifie si tu peux faire une recherche manuelle sur le site. Si oui, l'API est bridée.")
                return

            results = data.get("data", {}).get("searchPeople", {}).get("results", [])
            print(f"✅ Enfin ! {len(results)} profils trouvés.")
            
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=4, ensure_ascii=False)

        else:
            print(f"❌ Erreur HTTP {response.status_code}")
            print(f"Contenu : {response.text}")

    except Exception as e:
        print(f"❌ Erreur : {e}")

if __name__ == "__main__":
    fetch_leadiq_personas()