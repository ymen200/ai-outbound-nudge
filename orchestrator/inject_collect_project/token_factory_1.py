import httpx
from openai import OpenAI

# Client Token Factory
http_client = httpx.Client(verify=False)

client = OpenAI(
    api_key="sk-83d910e10b1e44658ea00d57a407ecac",
    base_url="https://tokenfactory.esprit.tn/api",
    http_client=http_client
)

# Prompt simple
prompt = "Explique en quelques phrases ce qu'est l'intelligence artificielle."

response = client.chat.completions.create(
    model="hosted_vllm/Llama-3.1-70B-Instruct",
    messages=[
        {
            "role": "system",
            "content": "Tu es un assistant utile."
        },
        {
            "role": "user",
            "content": prompt
        }
    ],
    temperature=0.7,
    max_tokens=200
)

print("=== Réponse du LLM ===")
print(response.choices[0].message.content)