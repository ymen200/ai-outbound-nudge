from google import genai
import os
from dotenv import load_dotenv

# Charger la clé API
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")


def list_working_models():
    if not API_KEY:
        print("❌ Erreur : GEMINI_API_KEY non trouvée.")
        return

    client = genai.Client(api_key=API_KEY)

    print("🔍 Scan des modèles disponibles...")
    print("-" * 60)

    try:
        models = client.models.list()

        usable_models = []

        for m in models:
            name = m.name
            methods = getattr(m, "supported_generation_methods", [])

            print(f"📌 {name}")
            print(f"   ➤ Méthodes: {methods}")

            # 👉 Filtrer les modèles utilisables avec generateContent
            if methods and "generateContent" in methods:
                usable_models.append(name)
                print("   ✅ Utilisable pour generate_content")

            print("-" * 60)

        print("\n🎯 Modèles que tu peux utiliser DIRECTEMENT :")
        for m in usable_models:
            print(f"✅ {m}")

    except Exception as e:
        print(f"❌ Erreur : {e}")


if __name__ == "__main__":
    list_working_models()