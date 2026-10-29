import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("FULLENRICH_API_KEY")
if not API_KEY:
    raise ValueError("FULLENRICH_API_KEY manquante dans .env")
BASE_URL = "https://app.fullenrich.com/api/v2"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

def search_personas(company_domain, company_name=None):
    """Recherche les personas avec des filtres plus souples."""
    url = f"{BASE_URL}/people/search"
    
    # On construit un payload plus "large"
    payload = {
        "offset": 0,
        "limit": 10,
        "current_company_domains": [
            {
                "value": company_domain,
                "exact_match": False, # On passe à False pour être moins strict
                "exclude": False
            }
        ]
    }

    # Si on a un nom d'entreprise, on l'ajoute pour aider l'indexation
    if company_name:
        payload["current_company_names"] = [
            {
                "value": company_name,
                "exact_match": False,
                "exclude": False
            }
        ]

    print(f"🔍 Recherche de personas pour : {company_domain} ({company_name or 'domaine seul'})...")
    
    try:
        response = requests.post(url, json=payload, headers=HEADERS, timeout=30)
        
        # DEBUG : Affiche la réponse brute si on ne trouve rien
        if response.status_code != 200:
            print(f"❌ Erreur API ({response.status_code}): {response.text}")
            return []

        data = response.json()
        
        # Vérification de la structure de réponse (certaines APIs v2 utilisent 'data' au lieu de 'results')
        results = data.get('results', data.get('data', []))
        
        if not results:
            print("⚠️ Aucun résultat. Voici la réponse brute pour déboguer :")
            print(json.dumps(data, indent=2))
        else:
            print(f"✅ {len(results)} personas trouvés.")
            
        return results

    except Exception as e:
        print(f"❌ Erreur lors de la recherche : {e}")
        return []

def bulk_enrich_personas(people_list, company_domain):
    """Envoie la liste de personnes pour un enrichissement en masse."""
    if not people_list:
        return

    url = f"{BASE_URL}/contact/enrich/bulk"
    
    enrich_data = []
    for person in people_list:
        # On récupère le LinkedIn URL qui est crucial pour l'enrichissement
        linkedin_url = person.get("professional_network_url") or person.get("linkedin_url")
        
        if linkedin_url:
            enrich_data.append({
                "first_name": person.get("first_name"),
                "last_name": person.get("last_name"),
                "domain": company_domain,
                "linkedin_url": linkedin_url,
                "enrich_fields": ["contact.work_emails", "contact.personal_emails", "contact.phones"]
            })

    if not enrich_data:
        print("⚠️ Aucun profil avec URL LinkedIn trouvé dans les résultats.")
        return

    payload = {
        "name": f"Enrichissement {company_domain}",
        "data": enrich_data
    }

    print(f"🚀 Envoi de {len(enrich_data)} personas pour enrichissement bulk...")
    
    try:
        response = requests.post(url, json=payload, headers=HEADERS, timeout=30)
        response.raise_for_status()
        res_data = response.json()
        
        with open("bulk_enrich_request.json", "w", encoding="utf-8") as f:
            json.dump(res_data, f, indent=4)
            
        print(f"✅ Requête Bulk envoyée ! ID : {res_data.get('id')}")
        return res_data
    except Exception as e:
        print(f"❌ Erreur lors de l'enrichissement : {e}")

if __name__ == "__main__":
    # Test avec des paramètres plus explicites
    # Essaye avec un nom d'entreprise connu
    target_domain = "vermeg.com"
    target_name = "vermeg" 
    
    personas = search_personas(target_domain, target_name)
    
    if personas:
        bulk_enrich_personas(personas, target_domain)