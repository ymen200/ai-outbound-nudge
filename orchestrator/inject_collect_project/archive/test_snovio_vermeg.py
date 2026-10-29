import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION SNOV.IO ---
CLIENT_ID = os.getenv("SNOVIO_CLIENT_ID")
CLIENT_SECRET = os.getenv("SNOVIO_CLIENT_SECRET")
if not CLIENT_ID or not CLIENT_SECRET:
    raise ValueError("SNOVIO_CLIENT_ID et SNOVIO_CLIENT_SECRET doivent être définies dans .env")
DOMAIN = "vermeg.com"
OUTPUT_FILE = "vermeg_staff_snovio_enriched.json"

def get_access_token():
    """Récupère le token d'accès OAuth2 pour Snov.io"""
    auth_url = "https://api.snov.io/v1/oauth/access_token"
    data = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'client_credentials'
    }
    try:
        response = requests.post(auth_url, data=data)
        if response.status_code == 200:
            return response.json().get('access_token')
        else:
            print(f"❌ Erreur Auth : {response.text}")
            return None
    except Exception as e:
        print(f"❌ Erreur connexion Snov.io : {e}")
        return None

def fetch_vermeg_staff(token):
    """Récupère le staff avec enrichissement LinkedIn et localisation"""
    # L'endpoint v2 offre plus de détails
    search_url = "https://api.snov.io/v2/domain-emails-with-info"
    
    params = {
        'domain': DOMAIN,
        'limit': 3,          # Toujours limité à 3 pour ton test crédits
        'lastId': 0,
        'type': 'all'        
    }
    
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    print(f"📡 Connexion Snov.io établie. Extraction du staff de {DOMAIN}...")

    try:
        response = requests.get(search_url, params=params, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            emails_list = data.get('emails', [])
            
            final_staff = []
            for person in emails_list:
                # Snov.io renvoie souvent les réseaux sociaux dans une liste d'objets ou de liens
                social_links = person.get('social', [])
                linkedin_url = "Non trouvé"
                
                # Recherche spécifique du lien LinkedIn dans les données sociales
                if social_links:
                    for link in social_links:
                        if 'linkedin.com' in str(link):
                            linkedin_url = link
                            break

                final_staff.append({
                    "full_name": f"{person.get('firstName', '')} {person.get('lastName', '')}".strip(),
                    "email": person.get('email'),
                    "job_title": person.get('position') or "Non spécifié",
                    "linkedin": linkedin_url,
                    "location": person.get('locality') or "Tunisia (Default)", # Snov donne souvent la ville
                    "status": person.get('status') or "verified", # Indique si l'email est valide
                    "source": "Snov.io Pro Search"
                })

            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(final_staff, f, indent=4, ensure_ascii=False)

            print(f"✅ Terminé ! {len(final_staff)} profils enrichis sauvegardés.")
            print(f"📄 Fichier : {OUTPUT_FILE}")
            
        else:
            print(f"❌ Erreur API Snov : {response.status_code} - {response.text}")

    except Exception as e:
        print(f"❌ Erreur système : {e}")

if __name__ == "__main__":
    token = get_access_token()
    if token:
        fetch_vermeg_staff(token)
    else:
        print("💡 Problème d'authentification. Vérifie tes identifiants Snov.io.")