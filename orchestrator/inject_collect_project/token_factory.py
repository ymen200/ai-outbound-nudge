"""
Script de test pour l'API Token Factory (ESPRIT).

Le script original semblait "plante" car :
- aucun message n'etait affiche avant l'appel LLM ;
- httpx n'avait pas de timeout -> attente infinie si l'API ne repond pas.
"""

import argparse
import os
import sys

import httpx
from openai import APIConnectionError, APITimeoutError, OpenAI

import config

BASE_URL = "https://tokenfactory.esprit.tn/api"
DEFAULT_MODEL = "hosted_vllm/Llama-3.1-70B-Instruct"
DEFAULT_PROMPT = "Explique en quelques phrases ce qu'est l'intelligence artificielle."


def _default_timeout() -> float:
  value = os.getenv("REQUEST_TIMEOUT", "120")
  try:
    return float(value)
  except ValueError:
    return 120.0


def build_http_client(timeout_seconds: float) -> httpx.Client:
  return httpx.Client(
    verify=False,
    timeout=httpx.Timeout(timeout_seconds, connect=10.0),
  )


def ping_api(timeout_seconds: float) -> bool:
  """Verifie que le serveur Token Factory est joignable."""
  print(f"[1/3] Ping {BASE_URL} (timeout {timeout_seconds}s)...", flush=True)
  try:
    response = httpx.get(BASE_URL, timeout=timeout_seconds, verify=False)
    print(f"      -> HTTP {response.status_code}", flush=True)
    return response.status_code < 500
  except httpx.TimeoutException:
    print("      -> ERREUR: le serveur ne repond pas (timeout).", flush=True)
    return False
  except httpx.RequestError as exc:
    print(f"      -> ERREUR reseau: {exc}", flush=True)
    return False


def call_llm(prompt: str, model: str, timeout_seconds: float, max_tokens: int) -> str:
  print(f"[2/3] Appel LLM ({model})...", flush=True)
  print(f"      Timeout lecture: {timeout_seconds}s", flush=True)

  http_client = build_http_client(timeout_seconds)
  client = OpenAI(
    api_key=config.ESPRIT_TOKEN_FACTORY_KEY,
    base_url=BASE_URL,
    http_client=http_client,
    timeout=timeout_seconds,
  )

  response = client.chat.completions.create(
    model=model,
    messages=[
      {"role": "system", "content": "Tu es un assistant utile."},
      {"role": "user", "content": prompt},
    ],
    temperature=0.7,
    max_tokens=max_tokens,
  )
  return response.choices[0].message.content


def main() -> int:
  parser = argparse.ArgumentParser(description="Test de l'API Token Factory ESPRIT.")
  parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Prompt a envoyer au LLM.")
  parser.add_argument("--model", default=DEFAULT_MODEL, help="Modele Token Factory.")
  parser.add_argument(
    "--timeout",
    type=float,
    default=_default_timeout(),
    help="Timeout HTTP en secondes pour l'appel LLM.",
  )
  parser.add_argument("--max-tokens", type=int, default=200, help="Nombre max de tokens en sortie.")
  parser.add_argument(
    "--ping-only",
    action="store_true",
    help="Teste uniquement la connectivite HTTP (sans appel LLM).",
  )
  args = parser.parse_args()

  if not config.ESPRIT_TOKEN_FACTORY_KEY:
    print("ERREUR: ESPRIT_TOKEN_FACTORY_KEY manquante dans le fichier .env")
    return 1

  if not ping_api(timeout_seconds=min(args.timeout, 15.0)):
    print(
      "\nLe serveur Token Factory est injoignable ou trop lent.\n"
      "Verifiez votre connexion (VPN ESPRIT, pare-feu, proxy) ou l'etat du service."
    )
    return 1

  if args.ping_only:
    print("\nPing OK. Utilisez sans --ping-only pour tester le LLM.")
    return 0

  try:
    content = call_llm(
      prompt=args.prompt,
      model=args.model,
      timeout_seconds=args.timeout,
      max_tokens=args.max_tokens,
    )
  except APITimeoutError:
    print(
      f"\n[3/3] ERREUR: timeout apres {args.timeout}s.\n"
      "Le modele Llama-70B peut etre lent ou indisponible cote serveur.\n"
      "Reessayez avec un timeout plus long: python token_factory.py --timeout 180"
    )
    return 1
  except APIConnectionError as exc:
    print(f"\n[3/3] ERREUR de connexion: {exc}")
    return 1
  except Exception as exc:
    print(f"\n[3/3] ERREUR: {type(exc).__name__}: {exc}")
    return 1

  print("\n=== Reponse du LLM ===")
  print(content)
  return 0


if __name__ == "__main__":
  sys.exit(main())
