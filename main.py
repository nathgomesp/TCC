import network
import urequests
import time
import dht
import gc
from machine import Pin, ADC, I2C
from i2c_lcd import I2cLcd

# === CONFIGURAÇÕES ===
SSID = "DUMB HUSK"
SENHA = "2wanning"
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
VALOR_SECO = 710
VALOR_UMIDO = 314

# === VARIÁVEIS DE CONTROLE ===
tempo_inicio_bomba = None
tempo_maximo_bomba = 30
tempo_espera_minima = 300
ultimo_desligamento = None
bombaLigada = False
umidade_filtrada = None
tempo_umidade_alta = None
tempo_umidade_requerida = 30
intensidade_real_aplicada = 0  # tempo total de irrigação aplicada em segundos
falhas_consecutivas = 0

# === PLANTA MONITORADA ===
planta = "alface"

# === FAIXAS IDEAIS DE TEMPERATURA POR PLANTA ===
faixas_temperatura = {
    "alface": {
        "frio": (0, 17),
        "medio": (18, 24),
        "quente": (25, 40)
    }
}

# === FAIXAS IDEAIS DE UMIDADE POR PLANTA ===
faixas_umidade = {
    "alface": {
        "seco": (0, 50),
        "ideal": (60, 65),
        "umido": (70, 100)
    }
}

# === FUNÇÕES ===
def enviar_novo_canal(intensidade_real_aplicada):
    try:
        payload = (
            f"{NOVO_CANAL_URL}?api_key={NOVO_CANAL_API_KEY}"
            f"&field1={intensidade_real_aplicada}"
        )
        resposta = urequests.get(payload, timeout=10)
        if resposta.status_code != 200:
            print(f"[ERRO] Segundo canal retornou status {resposta.status_code}")
        resposta.close()
        gc.collect()
        print(f"[ENVIO] Intensidade real enviada ao segundo canal: {intensidade_real_aplicada}s")
    except Exception as e:
        print("Falha ao enviar para o segundo canal:", e)

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

        if isinstance(dados, dict):
            return round(dados.get("chuva_mm", 0), 2)
        else:
            print("Formato inesperado da resposta:", dados)
            return -1
    except Exception as e:
        print("Erro ao obter previsão de chuva:", repr(e))
        return -1

def filtrar_exponencial(leitura, anterior, alpha=0.15):
    return leitura if anterior is None else int(alpha * leitura + (1 - alpha) * anterior)

def solo_seco(umidade):
    return max(0, min(1, (30 - umidade) / 30)) if umidade <= 30 else 0

def solo_medio(umidade):
    if 20 <= umidade <= 80:
        return (umidade - 20) / 30 if umidade <= 50 else (80 - umidade) / 30
    return 0

def solo_umido(umidade):
    return max(0, min(1, (umidade - 70) / 30)) if umidade >= 70 else 0

def temp_frio(valor, planta):
    faixa = faixas_temperatura[planta]["frio"]
    return max(0, min(1, (faixa[1] - valor) / (faixa[1] - faixa[0]))) if valor <= faixa[1] else 0

def temp_medio(valor, planta):
    faixa = faixas_temperatura[planta]["medio"]
    if valor < faixa[0] - 1 or valor > faixa[1] + 1:
        return 0
    meio = (faixa[0] + faixa[1]) / 2
    if valor <= meio:
        return max(0.01, (valor - faixa[0]) / (meio - faixa[0])) if meio != faixa[0] else 1.0
    else:
        return max(0.01, (faixa[1] - valor) / (faixa[1] - meio)) if faixa[1] != meio else 1.0

def temp_quente(valor, planta):
    faixa = faixas_temperatura[planta]["quente"]
    if valor < faixa[0]:
        return 0
    return min(1.0, (valor - faixa[0]) / (faixa[1] - faixa[0]) * 1.5)  # escala mais agressiva

def calcular_irrigacao(umidade_solo, temp, chuva):
    # membros de umidade (fuzzy)
    seco = solo_seco(umidade_solo)
    medio = solo_medio(umidade_solo)
    umido = solo_umido(umidade_solo)

    # membros de temperatura (fuzzy)
    frio = temp_frio(temp, planta)
    tmedio = temp_medio(temp, planta)
    quente = temp_quente(temp, planta)

    # evitar anulamento total usando mínimos e um fator de temperatura permissivo
    temp_factor = max(frio, tmedio, quente, 0.05)    # garante mínimo para não zerar tudo
    forte = seco * temp_factor
    media = medio * max(tmedio, 0.05)
    fraca = umido * max(frio, 0.02)

    # pesos escalados para permitir valores maiores quando necessário
    PESO_FORTE = 600.0
    PESO_MEDIA = 300.0
    PESO_FRACA = 60.0

    numerador = forte * PESO_FORTE + media * PESO_MEDIA + fraca * PESO_FRACA
    denominador = (forte + media + fraca + 0.01)
    irrigacao_bruta = numerador / denominador

    # ajuste por chuva (mantém redução caso chova)
    if chuva >= 0:
        irrigacao_bruta *= max(0.2, 1 - min(chuva / 10, 0.8))

    # garantia mínima em solo muito seco (em bruto)
    if irrigacao_bruta < 1 and seco > 0.5:
        irrigacao_bruta = 60.0
        print("[AJUSTE] Irrigação mínima aplicada por solo seco (bruto).")

    return irrigacao_bruta

def enviar_thingspeak(umidade_solo, temp_local, umidade_ar, irrigacao, chuva, umidade_alface):
    try:
        atividade = 1
        payload = (
            f"{THINGSPEAK_URL}?api_key={THINGSPEAK_API_KEY}"
            f"&field1={umidade_solo}&field2={temp_local}&field3={umidade_ar}"
            f"&field4={chuva}&field5={irrigacao}&field6={atividade}"
            f"&field8={umidade_alface}"
        )
        resposta = urequests.get(payload, timeout=10)
        if resposta.status_code != 200:
            print(f"[ERRO] ThingSpeak retornou status {resposta.status_code}")
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
            print("[REDE] Wi-Fi desconectado. Reiniciando interface...")
            wlan.active(False)
            time.sleep(2)
            wlan.active(True)
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

        faixa = faixas_umidade[planta]["ideal"]
        if umidade_solo < faixa[0]:
            irrigacao = int(irrigacao * 1.2)
        elif umidade_solo > faixa[1]:
            irrigacao = int(irrigacao * 0.6)
        if umidade_solo >= faixa[1]:
            irrigacao = 0


        print(f"[STATUS] Tempo de irrigação ajustado: {irrigacao} segundos")
        tempo_irrigacao_ciclo = min(irrigacao, tempo_maximo_bomba)
        if irrigacao > tempo_maximo_bomba:
            print(f"[AVISO] Tempo de irrigação ({irrigacao}s) limitado para {tempo_maximo_bomba}s por segurança.")

        if bombaLigada:
            if time.time() - tempo_inicio_bomba >= tempo_irrigacao_ciclo:
                intensidade_real_aplicada += tempo_irrigacao_ciclo
                bombaLigada = False
                ultimo_desligamento = time.time()
                print(f"[CICLO] Fim do ciclo de {tempo_irrigacao_ciclo}s. Bomba desligada.")
                print(f"[LOG] Intensidade real acumulada: {intensidade_real_aplicada}s")
            elif umidade_solo >= faixa[1]:
                if tempo_umidade_alta is None:
                    tempo_umidade_alta = time.time()
                elif time.time() - tempo_umidade_alta >= tempo_umidade_requerida:
                    bombaLigada = False
                    ultimo_desligamento = time.time()
                    print("[CICLO] Saturação atingida. Bomba desligada antes do fim do ciclo.")
                    print(f"[LOG] Irrigação total aplicada até atingir ideal: {intensidade_real_aplicada}s")
                    intensidade_real_aplicada = 0
            else:
                tempo_umidade_alta = None
        else:
            tempo_umidade_alta = None
            tempo_passado = time.time() - ultimo_desligamento if ultimo_desligamento else tempo_espera_minima + 1
            print(f"[CICLO] Tempo desde último desligamento: {tempo_passado:.1f}s")

            if tempo_passado > tempo_espera_minima and umidade_solo < faixa[0] and tempo_irrigacao_ciclo > 10:
                bombaLigada = True
                tempo_inicio_bomba = time.time()
                print(f"[CICLO] Iniciando ciclo de irrigação de {tempo_irrigacao_ciclo} segundos.")

        RELAY_PIN.value(1 if bombaLigada else 0)
        print(f"[STATUS] Bomba {'LIGADA' if bombaLigada else 'DESLIGADA'}")

        try:
            lcd.clear()
            lcd.putstr("Solo:\n")
            lcd.putstr(f"{umidade_solo}% {temp_local}C")
        except Exception as e:
            print("Erro no LCD:", repr(e))

       

        umidade_alface = umidade_solo if planta == "alface" else 0
        enviar_thingspeak(umidade_solo, temp_local, umidade_ar, irrigacao, chuva, umidade_alface)
        enviar_novo_canal(intensidade_real_aplicada)

        time.sleep(27)

    except Exception as e:
        falhas_consecutivas += 1
        print(f"[ERRO] {repr(e)} | Falhas consecutivas: {falhas_consecutivas}")
        if falhas_consecutivas >= 5:
            print("[RECUPERAÇÃO] Muitas falhas seguidas. Reiniciando sistema...")
            import machine
            machine.reset()
        time.sleep(27)
