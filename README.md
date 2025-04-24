# 🤖 Bot de Monitoramento de Jogos ao Vivo - Telegram

Este bot permite consultar e monitorar jogos de futebol ao vivo com comandos no Telegram.

---

## ✅ Comandos Disponíveis

| Comando       | Ação                                                                |
|---------------|---------------------------------------------------------------------|
| `/start`      | Mensagem de boas-vindas e menu de comandos                          |
| `/ajuda`      | Mostra todos os comandos disponíveis                                |
| `/jogos`      | Lista todos os jogos ao vivo no momento                             |
| `/tendencias` | Mostra jogos ao vivo com alta tendência de escanteios (média ≥ 10)  |
| `/proximos`   | Lista jogos que irão começar nas próximas 3 horas                   |
| `/config`     | Mostra status da API-Football (uso diário, plano, etc)              |

---

## ⚙️ Como configurar no Replit

1. Suba todos os arquivos no seu projeto do Replit
2. Vá no painel lateral e clique em **Tools → Configuration**
3. No campo **Run Command**, insira:

```bash
python3 bot_main.py
```

4. Clique em **Save**
5. Clique no botão **Run**

---

## 🔐 Variáveis Necessárias

Adicione as seguintes variáveis em **"Secrets"** (ícone de 🔑 no topo ou lateral):

- `API_FOOTBALL_KEY` → sua chave da API-Football
- `TELEGRAM_TOKEN` → token do seu bot no Telegram

---

## 📦 Arquivos incluídos

- `bot_main.py` → Bot com todos os comandos
- `.replit` → (usado para execução automática com python3)
- `README.md` → Este guia

---

Desenvolvido com 💙 para ajudar você a monitorar futebol e apostas em tempo real.
