from google import genai
import os
from dotenv import load_dotenv

# Charger ta clé API
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

def list_working_models():
    if not API_KEY:
        print("❌ Erreur : GEMINI_API_KEY non trouvée.")
        return

    client = genai.Client(api_key=API_KEY)

    print(f"🔍 Scan des modèles disponibles via le nouveau SDK...")
    print("-" * 50)
    
    try:
        # On liste tous les modèles. Dans cette version, m.name contient l'ID direct.
        models = client.models.list()
        for m in models:
            # On affiche le nom que tu dois copier dans ton code
            print(f"✅ Modèle trouvé : {m.name}")
            
    except Exception as e:
        print(f"❌ Erreur lors de la récupération : {e}")

    print("-" * 50)
    print("💡 Conseil : Utilise le nom complet affiché (ex: 'gemini-1.5-flash').")

if __name__ == "__main__":
    list_working_models()