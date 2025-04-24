# Robô de Alertas de Escanteios no Telegram

Este projeto envia alertas de escanteios no Telegram para partidas ao vivo que atendam critérios específicos.

## ✅ Requisitos

- Python 3.12 instalado
- Biblioteca `pip`
- Conta no [API-Football](https://dashboard.api-football.com/)
- Bot do Telegram e seu Chat ID

## 🚀 Como Rodar Localmente

1. Instale as dependências:
```bash
pip install -r requirements.txt
```

2. Crie um arquivo `.env` baseado no `.env.example` com suas credenciais.

3. Execute o robô:
```bash
python main.py
```

## ☁️ Como Subir para a Railway (nuvem)

1. Crie uma conta em https://railway.app
2. Crie um novo projeto e conecte este código (suba para GitHub ou envie os arquivos)
3. Adicione as variáveis de ambiente no painel da Railway (baseadas no `.env`)
4. Configure o comando de execução:
```bash
python main.py
```
