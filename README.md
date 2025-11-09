# 💧 Sistema de Irrigação Inteligente com IoT para Agricultura Familiar

Este projeto utiliza algoritmo fuzzy para determinar quando irrigar e por quanto tempo, otimizando o consumo hídrico em ambientes de agricultura familiar. 
Ele integra sensores e uma interface LCD para exibição de dados em tempo real, além de API com um site meteorológico e também com plataforma Iot ThingSpeak.

---

## 📁 Estrutura do Repositório

### 🔹 Códigos Principais (Versão Final)

Estes arquivos compõem a versão final e funcional do projeto:

- **`main.py`**  
  Código principal que integra todos os módulos.  
  ⚠️ **Atenção:** É necessário alterar o nome da rede Wi-Fi e a senha diretamente no código para que o dispositivo se conecte corretamente.  
  Procure pelas variáveis:
  ```python
  SSID = "SuaRedeWiFi"
  PASSWORD = "SuaSenha"

`i2c_lcd.py` e `lcd_api.py` Módulos responsáveis pela comunicação com o display LCD via protocolo I2C. Permitem que os dados sejam exibidos de forma clara e eficiente.

🧪 Códigos Secundários / Testes
Arquivos utilizados para testes, versões anteriores ou ambientes específicos:

`main (código teste 1).py` Versão de teste do código inicial (base), usada para validações iniciais. Caso usarem, deverá renomear para "main.py".

`main python anywhere.py` código para rodar no PythonAnywhere.

`Código I.A Preditiva - Economia de Água.ipynb` Notebook Jupyter com análises com construção da inteligência preditiva.


📦 Outros Arquivos
`requirements.txt` faz o download das dependências presentes no `main python anywhere.py`.

⚠️ — Atenção
Tanto `requirements.txt` quanto `main python anywhere.py` não precisam ser rodados, pois o link fixo já foi criado pelho PythonAnywhere e está presente no código principal do micropython `main.py`.
