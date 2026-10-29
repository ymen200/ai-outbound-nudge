import os
from apify_client import ApifyClient

class ApifyLeadsTester:
    def __init__(self, api_token):
        self.client = ApifyClient(api_token)

    def scrape_leads(self, domain, country, limit=10, actor_name="pipelinelabs/lead-scraper-apollo-zoominfo-lusha-ppe"):
        print(f"🚀 Lancement de l'acteur : {actor_name}...")
        
        # Structure de données validée
        run_input = {
            "companyLocationCountryIncludes": [country],
            "companyDomainIncludes": [domain],
            "totalResults": limit
        }

        try:
            run = self.client.actor(actor_name).call(run_input=run_input)
            
            dataset_id = run.default_dataset_id
            items = self.client.dataset(dataset_id).list_items().items
            
            print(f"✅ Scraping terminé. {len(items)} leads trouvés.")
            return items

        except Exception as e:
            print(f"❌ Erreur critique : {e}")
            return []

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    APIFY_TOKEN = os.getenv("APIFY_API_KEY")
    if not APIFY_TOKEN:
        raise ValueError("APIFY_API_KEY manquante dans .env")
    
    tester = ApifyLeadsTester(api_token=APIFY_TOKEN)
    
    # Exécution
    leads = tester.scrape_leads(
        domain="nestle.com", 
        country="Switzerland", 
        limit=20
    )
    
    # Affichage détaillé
    print("\n--- DÉTAILS DES LEADS ---")
    if leads:
        for i, lead in enumerate(leads, 1):
            # Extraction des champs
            first_name = lead.get('firstName', 'N/A')
            last_name = lead.get('lastName', 'N/A')
            full_name = lead.get('fullName', f"{first_name} {last_name}")
            email = lead.get('email', 'N/A')
            title = lead.get('title', 'N/A')
            linkedin_url = lead.get('linkedinUrl', 'N/A')
            
            # Nouveaux champs demandés
            company_name = lead.get('companyName', 'N/A')
            phone_number = lead.get('phoneNumber', 'N/A')
            
            # Affichage formaté
            print(f"{i}. {full_name}")
            print(f"   Prénom: {first_name} | Nom: {last_name}")
            print(f"   Entreprise: {company_name}")
            print(f"   Poste: {title}")
            print(f"   Email: {email}")
            print(f"   Téléphone: {phone_number}")
            print(f"   LinkedIn: {linkedin_url}")
            print("-" * 30)
    else:
        print("Aucun lead trouvé avec cette configuration.")
