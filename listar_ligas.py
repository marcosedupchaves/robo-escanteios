import os
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("API_FOOTBALL_KEY")

# Opcional: filtrar por temporada, ex: 2024 ou 2025
params = {
    "season": 2024
}

resp = requests.get(
    "https://v3.football.api-sports.io/leagues",
    headers={"x-apisports-key": API_KEY},
    params=params
)
data = resp.json().get("response", [])

print(f"{'ID':<6} {'Liga':<30} {'País'}")
print("-"*60)
for entry in data:
    liga = entry["league"]
    country = entry["country"]["name"]
    print(f"{liga['id']:<6} {liga['name']:<30} {country}")
