import network
import urequests
import time
import dht
import gc
from machine import Pin, ADC, I2C
from i2c_lcd import I2cLcd

# === CONFIGURAÇÕES ===
SSID = "Nome_do_wifi"
SENHA = "senha_do_wifi"
OWM_API_KEY = "572f825868ba5390c9743c1dff4329e1"
NOVO_CANAL_API_KEY = "LKLTO0MJR5DRCB9A"  # substitua pela sua Write API Key
NOVO_CANAL_URL = "http://api.thingspeak.com/update"
LATITUDE = -23.5505
LONGITUDE = -46.6333
THINGSPEAK_API_KEY = "U07M4R9UPNNHLDYX"
THINGSPEAK_URL = "http://api.thingspeak.com/update"

# === HARDWARE ===
SOIL_PIN = ADC(0)
RELAY_PIN = Pin(13, Pin.OUT)
DHT_SENSOR = dht.DHT11(Pin(5))
i2c = I2C(scl=Pin(14), sda=Pin(12), freq=400000)
lcd = I2cLcd(i2c, 0x27, 2, 16)

# === CALIBRAÇÃO DO SENSOR CAPACITIVO ===
VALOR_SECO = 640
VALOR_UMIDO = 340

# === VARIÁVEIS DE CONTROLE ===
tempo_inicio_bomba = None
tempo_maximo_bomba = 30
tempo_espera_minima = 300
ultimo_desligamento = None
bombaLigada = False
umidade_filtrada = None
tempo_umidade_alta = None
tempo_umidade_requerida = 30

# === PLANTA MONITORADA ===
planta = "alface"

# === FAIXAS IDEAIS DE UMIDADE POR PLANTA ===
faixas_umidade = {
    "alface": (60, 65)
}

# === FUNÇÕES ===
def conectar_wifi(ssid, senha):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(ssid, senha)
    inicio = time.time()
    while not wlan.isconnected():
        if time.time() - inicio > 10:
            print("Falha ao conectar ao Wi-Fi")
            return False
    print("Wi-Fi conectado:", wlan.ifconfig())
    return True

def chuva_prevista():
    try:
        resposta = urequests.get("http://davidjrxs.pythonanywhere.com/chuva", timeout=10)
        dados = resposta.json()
        resposta.close()
        return round(dados.get("chuva_mm", 0), 2)
    except Exception as e:
        print("Erro ao obter previsão de chuva:", e)
        return -1


def filtrar_exponencial(leitura, anterior, alpha=0.3):
    return leitura if anterior is None else int(alpha * leitura + (1 - alpha) * anterior)

def solo_seco(umidade):
    return max(0, min(1, (30 - umidade) / 30)) if umidade <= 30 else 0

def solo_medio(umidade):
    if 20 <= umidade <= 80:
        return (umidade - 20) / 30 if umidade <= 50 else (80 - umidade) / 30
    return 0

def solo_umido(umidade):
    return max(0, min(1, (umidade - 70) / 30)) if umidade >= 70 else 0

def temp_frio(valor):
    return max(0, min(1, (20 - valor) / 10)) if valor <= 20 else 0

def temp_medio(valor):
    if 21 <= valor <= 30:
        return (valor - 21) / 4.5 if valor <= 25.5 else (30 - valor) / 4.5
    return 0

def temp_quente(valor):
    return max(0, min(1, (valor - 31) / 10)) if valor >= 31 else 0

def calcular_irrigacao(umidade_solo, temp, chuva):
    seco = solo_seco(umidade_solo)
    medio = solo_medio(umidade_solo)
    umido = solo_umido(umidade_solo)

    def temp_medio_ajustado(valor):
        if 21 <= valor <= 30:
            return max(0.1, (valor - 21) / 4.5 if valor <= 25.5 else (30 - valor) / 4.5)
        return 0

    frio = temp_frio(temp)
    tmedio = temp_medio_ajustado(temp)
    quente = temp_quente(temp)

    forte = seco * max(quente, tmedio, frio)
    media = medio * tmedio
    fraca = umido * frio

    irrigacao = (forte * 300 + media * 150 + fraca * 30) / (forte + media + fraca + 0.01)

    if chuva >= 0:
        irrigacao *= max(0.2, 1 - min(chuva / 10, 0.8))

    irrigacao = int(irrigacao)

    if irrigacao == 0 and seco > 0.5:
        irrigacao = 60
        print("[AJUSTE] Irrigação mínima aplicada por solo seco.")

    return irrigacao

def enviar_thingspeak(umidade_solo, temp_local, umidade_ar, irrigacao, chuva, umidade_alface):
    try:
        atividade = 1
        payload = (
            f"{THINGSPEAK_URL}?api_key={THINGSPEAK_API_KEY}"
            f"&field1={umidade_solo}&field2={temp_local}&field3={umidade_ar}"
            f"&field4={chuva}&field5={irrigacao}&field6={atividade}"
            f"&field8={umidade_alface}"
        )
        resposta = urequests.get(payload)
        resposta.close()
        gc.collect()  # libera memória após envio
    except Exception as e:
        print("Falha ao enviar para ThingSpeak:", e)

# === LOOP PRINCIPAL ===
if not conectar_wifi(SSID, SENHA):
    print("Continuando sem Wi-Fi...")

while True:
    try:
        wlan = network.WLAN(network.STA_IF)
        if not wlan.isconnected():
            print("[REDE] Wi-Fi desconectado. Tentando reconectar...")
            conectar_wifi(SSID, SENHA)

        DHT_SENSOR.measure()
        temp_local = DHT_SENSOR.temperature()
        umidade_ar = DHT_SENSOR.humidity()
        chuva = chuva_prevista()

        solo = SOIL_PIN.read()
        print(f"\n[STATUS] Valor bruto do solo: {solo}")

        if solo <= 10 or solo >= 1023:
            print("[AVISO] Leitura inválida do sensor de solo.")
            time.sleep(15)
            continue

        umidade_solo = int((VALOR_SECO - solo) / (VALOR_SECO - VALOR_UMIDO) * 100)
        umidade_solo = max(0, min(100, umidade_solo))
        umidade_solo = filtrar_exponencial(umidade_solo, umidade_filtrada)
        umidade_filtrada = umidade_solo

        print(f"[STATUS] Umidade do solo: {umidade_solo}%")
        print(f"[STATUS] Temperatura: {temp_local}°C | Umidade do ar: {umidade_ar}%")
        print(f"[STATUS] Chuva prevista (6h): {chuva} mm")

        irrigacao = calcular_irrigacao(umidade_solo, temp_local, chuva)

        faixa = faixas_umidade.get(planta, (50, 70))
        if umidade_solo < faixa[0]:
            irrigacao = int(irrigacao * 1.2)
        elif umidade_solo > faixa[1]:
            irrigacao = int(irrigacao * 0.6)
        if umidade_solo >= faixa[1]:
            irrigacao = 0

        print(f"[STATUS] Tempo de irrigação ajustado: {irrigacao} segundos")

        if bombaLigada:
            if umidade_solo >= faixa[1]:
                if tempo_umidade_alta is None:
                    tempo_umidade_alta = time.time()
                elif time.time() - tempo_umidade_alta >= tempo_umidade_requerida:
                    bombaLigada = False
                    ultimo_desligamento = time.time()
                    print("[CICLO] Saturação atingida. Bomba desligada.")
            else:
                tempo_umidade_alta = None

            if time.time() - tempo_inicio_bomba > tempo_maximo_bomba:
                bombaLigada = False
                ultimo_desligamento = time.time()
                print("[CICLO] Tempo máximo atingido. Bomba desligada.")

        else:
            tempo_umidade_alta = None
            tempo_passado = time.time() - ultimo_desligamento if ultimo_desligamento else tempo_espera_minima + 1
            print(f"[CICLO] Tempo desde último desligamento: {tempo_passado:.1f}s")

            if umidade_solo < faixa[1] and tempo_passado > tempo_espera_minima:
                if ultimo_desligamento is None:
                    if umidade_solo < faixa[0] and irrigacao >= 100:
                        bombaLigada = True
                        tempo_inicio_bomba = time.time()
                        ultimo_desligamento = None
                        print("[CICLO] Primeiro ciclo iniciado.")
                else:
                    if irrigacao >= 100 or irrigacao == 0:
                        bombaLigada = True
                        tempo_inicio_bomba = time.time()
                        ultimo_desligamento = None
                        print("[CICLO] Segundo ciclo: irrigando até atingir 65%.")

        RELAY_PIN.value(1 if bombaLigada else 0)
        print(f"[STATUS] Bomba {'LIGADA' if bombaLigada else 'DESLIGADA'}")

        lcd.clear()
        lcd.putstr("Solo:\n")
        lcd.putstr(f"{umidade_solo}% {temp_local}C")
       

        umidade_alface = umidade_solo if planta == "alface" else 0
        enviar_thingspeak(umidade_solo, temp_local, umidade_ar, irrigacao, chuva, umidade_alface)


        time.sleep(27)

    except Exception as e:
        print("Erro no sistema:", e)
        time.sleep(27)
