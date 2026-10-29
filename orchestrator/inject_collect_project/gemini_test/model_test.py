from google import genai
import os
from dotenv import load_dotenv
import json

# Charger la clé API
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

def test_company_extraction(model_name="nano-banana-pro-preview"):
    if not API_KEY:
        print("❌ Erreur : GEMINI_API_KEY non trouvée.")
        return

    client = genai.Client(api_key=API_KEY)

    print(f"🚀 Test du modèle : {model_name}")
    print("-" * 50)

    # Prompt clair + structure JSON imposée
    prompt = """
Extract structured information about the following company and return ONLY valid JSON.

Company: NVIDIA

Expected JSON format:
{
  "name": "",
  "industry": "",
  "founded": "",
  "headquarters": "",
  "ceo": "",
  "description": "",
  "products": []
}
"""

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config={
                "temperature": 0.2,
                "response_mime_type": "application/json"  # 🔥 force JSON
            }
        )

        # Texte brut
        raw_output = response.text
        print("📦 Réponse brute :")
        print(raw_output)

        # Essayer de parser JSON
        try:
            data = json.loads(raw_output)
            print("\n✅ JSON parsé avec succès :")
            print(json.dumps(data, indent=2))
        except:
            print("\n⚠️ Impossible de parser le JSON automatiquement.")

    except Exception as e:
        print(f"❌ Erreur : {e}")

    print("-" * 50)


if __name__ == "__main__":
    test_company_extraction()