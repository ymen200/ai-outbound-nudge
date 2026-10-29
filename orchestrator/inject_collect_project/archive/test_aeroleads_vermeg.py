import requests
import json
import time
import os
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION AEROLEADS ---
AEROLEADS_API_KEY = os.getenv("AEROLEADS_API_KEY")
if not AEROLEADS_API_KEY:
    raise ValueError("AEROLEADS_API_KEY manquante dans .env")
COMPANY_NAME = "VERMEG"
OUTPUT_FILE = "vermeg_aeroleads_final_results.json"

# Liste des cibles avec les informations nécessaires pour les deux endpoints
TEST_PROFILES = [
    {
        "first_name": "Ines",
        "last_name": "Issa",
        "url": "https://www.linkedin.com/in/ines-i-4aa07971/"
    },
    {
        "first_name": "Boujemaa",
        "last_name": "Khaldi",
        "url": "https://www.linkedin.com/in/boujemaa-khaldi-9a0a3371"
    }
]

def get_by_linkedin(url):
    """Endpoint 1 : Extraction via URL LinkedIn"""
    api_url = "https://aeroleads.com/api/get_linkedin_details"
    params = {'api_key': AEROLEADS_API_KEY, 'linkedin_url': url}
    try:
        response = requests.get(api_url, params=params, timeout=15)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None

def get_by_name(first, last):
    """Endpoint 2 : Extraction via Nom + Entreprise (Fallback)"""
    api_url = "https://aeroleads.com/api/get_email_details"
    params = {
        'api_key': AEROLEADS_API_KEY,
        'first_name': first,
        'last_name': last,
        'company': COMPANY_NAME
    }
    try:
        response = requests.get(api_url, params=params, timeout=15)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None

def run_smart_scan():
    final_results = []
    print(f"🚀 Lancement de l'extraction intelligente pour {COMPANY_NAME}...")

    for p in TEST_PROFILES:
        full_name = f"{p['first_name']} {p['last_name']}"
        extracted_data = None
        method_used = "None"

        # --- TENTATIVE 1 : LINKEDIN ---
        print(f"🔍 [1/2] Tentative LinkedIn pour {full_name}...")
        data = get_by_linkedin(p['url'])
        
        # On vérifie si on a reçu des données valides (email ou téléphone)
        if data and (data.get('emails') or data.get('phone_numbers') or data.get('email')):
            print(f"✅ Succès via LinkedIn pour {full_name}")
            extracted_data = data
            method_used = "AeroLeads LinkedIn API"
        else:
            # --- TENTATIVE 2 : FALLBACK NOM/ENTREPRISE ---
            print(f"⚠️ Échec LinkedIn ou Profil privé. Lancement du Fallback (Nom/Entreprise)...")
            data_fallback = get_by_name(p['first_name'], p['last_name'])
            
            if data_fallback and (data_fallback.get('email') or data_fallback.get('emails')):
                print(f"✨ Succès via Fallback pour {full_name}")
                extracted_data = data_fallback
                method_used = "AeroLeads Email Finder API"
            else:
                print(f"❌ Échec total pour {full_name}. Aucune donnée trouvée.")

        if extracted_data:
            # Nettoyage pour l'affichage final
            email = extracted_data.get('email')
            if not email and extracted_data.get('emails'):
                email = extracted_data['emails'][0].get('address')
            
            phone = extracted_data.get('phone_number') or extracted_data.get('phone')
            if not phone and extracted_data.get('phone_numbers'):
                phone = extracted_data['phone_numbers'][0]

            final_results.append({
                "full_name": full_name,
                "email": email or "Non trouvé",
                "phone": phone or "Non trouvé",
                "method": method_used,
                "raw_data": extracted_data
            })
        
        time.sleep(2) # Respect du rate limit

    # Sauvegarde
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_results, f, indent=4, ensure_ascii=False)

    print(f"\n📊 Rapport Final sauvegardé dans {OUTPUT_FILE}")
    for res in final_results:
        print(f"👤 {res['full_name']} | 📧 {res['email']} | 📞 {res['phone']} | 🛠️ {res['method']}")

if __name__ == "__main__":
    run_smart_scan()