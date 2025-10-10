from flask import Flask, jsonify
import requests

app = Flask(__name__)

# Dados fixos da localização e chave da API
OWM_API_KEY = "572f825868ba5390c9743c1dff4329e1"
LAT = -23.5505
LON = -46.6333

@app.route("/chuva")
def chuva():
    url = f"http://api.openweathermap.org/data/2.5/forecast?lat={LAT}&lon={LON}&appid={OWM_API_KEY}&units=metric"
    r = requests.get(url)
    dados = r.json()
    chuva_total = 0

    for bloco in dados.get("list", [])[:2]:  # próximos 6h
        chuva_total += bloco.get("rain", {}).get("3h", 0)

    return jsonify({"chuva_mm": round(chuva_total, 2)})

# Executa o servidor Flask na porta 5000
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

