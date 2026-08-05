# -*- coding: utf-8 -*-
"""
RADAR DE VOOS — VERSÃO NUVEM (GitHub Actions)
Corre de hora em hora, grátis, com o PC desligado.
Cadeia: Amadeus → SerpAPI → Travelpayouts (usa as chaves que existirem).
Alerta por Telegram quando o preço bate no ALVO ou fica abaixo do mínimo histórico.
Histórico guardado em precos.json dentro do próprio repositório.
"""
import json, os, time
import requests

# MODO MULTI-ROTAS: lista em ROTAS, formato "ORIG-DEST|dataIda|dataVolta|alvo;..."
# A cada hora o radar verifica UMA rota da lista, em rotação — cobertura ampla sem gastar quotas.
ROTAS_TXT = os.getenv("ROTAS",
    "LIS-FOR|2026-08-18|2026-09-14|650;"
    "LIS-CDG|2026-10-03|2026-10-07|130;"
    "LIS-FCO|2026-10-10|2026-10-14|150;"
    "LIS-LHR|2026-10-17|2026-10-20|140;"
    "LIS-AMS|2026-10-24|2026-10-27|160;"
    "LIS-MAD|2026-11-07|2026-11-10|90;"
    "LIS-GRU|2026-11-14|2026-11-28|550")
PAX = int(os.getenv("PAX", "1"))
TP_MARKER = os.getenv("TP_MARKER", "").strip()

def carregar_rotas():
    rotas = []
    for parte in ROTAS_TXT.split(";"):
        try:
            od, ida, volta, alvo = [x.strip() for x in parte.split("|")]
            o, d = od.split("-")
            rotas.append({"origem": o, "destino": d, "ida": ida, "volta": volta, "alvo": float(alvo)})
        except Exception:
            continue
    return rotas or [{"origem": "LIS", "destino": "FOR", "ida": "2026-08-18", "volta": "2026-09-14", "alvo": 650.0}]

# variáveis globais preenchidas por rota, a cada execução
ORIGEM = DESTINO = DATA_IDA = DATA_VOLTA = ""
ALVO = 0.0

NOMES = {
    "TP": "TAP Air Portugal", "LA": "LATAM", "AD": "Azul", "G3": "GOL", "VR": "Cabo Verde Airlines",
    "KL": "KLM", "LH": "Lufthansa", "AF": "Air France", "IB": "Iberia", "UX": "Air Europa",
    "BA": "British Airways", "LX": "SWISS", "TK": "Turkish Airlines", "AT": "Royal Air Maroc",
    "EK": "Emirates", "QR": "Qatar Airways", "EY": "Etihad", "AA": "American", "UA": "United",
    "DL": "Delta", "AC": "Air Canada", "CM": "Copa", "AV": "Avianca", "AZ": "ITA Airways",
}

def link_afiliado():
    u = f"https://www.aviasales.com/search/{ORIGEM}{DATA_IDA[8:10]}{DATA_IDA[5:7]}{DESTINO}"
    if DATA_VOLTA:
        u += f"{DATA_VOLTA[8:10]}{DATA_VOLTA[5:7]}"
    u += str(PAX)
    if TP_MARKER:
        u += f"?marker={TP_MARKER}"
    return u

# ── Motores (usa o primeiro que tiver chave e responder) ──
def motor_amadeus():
    k, s = os.getenv("AMADEUS_KEY", "").strip(), os.getenv("AMADEUS_SECRET", "").strip()
    if not k or not s:
        raise RuntimeError("sem credenciais")
    tok = requests.post("https://test.api.amadeus.com/v1/security/oauth2/token",
        data={"grant_type": "client_credentials", "client_id": k, "client_secret": s}, timeout=20).json()
    params = {"originLocationCode": ORIGEM, "destinationLocationCode": DESTINO,
              "departureDate": DATA_IDA, "adults": PAX, "currencyCode": "EUR", "max": 20}
    if DATA_VOLTA:
        params["returnDate"] = DATA_VOLTA
    r = requests.get("https://test.api.amadeus.com/v2/shopping/flight-offers",
        headers={"Authorization": "Bearer " + tok["access_token"]}, params=params, timeout=50).json()
    saida = []
    for o in r.get("data", []):
        try:
            cia = (o.get("validatingAirlineCodes") or ["??"])[0]
            seg = o["itineraries"][0]["segments"]
            saida.append({
                "companhia": NOMES.get(cia, cia), "preco": round(float(o["price"]["grandTotal"]) / PAX),
                "escalas": "Direto" if len(seg) == 1 else f"{len(seg)-1} escala(s)",
                "hora": seg[0]["departure"]["at"][11:16],
            })
        except Exception:
            continue
    if not saida:
        raise RuntimeError("0 ofertas")
    melhor = {}
    for x in saida:
        if x["companhia"] not in melhor or x["preco"] < melhor[x["companhia"]]["preco"]:
            melhor[x["companhia"]] = x
    return sorted(melhor.values(), key=lambda x: x["preco"])[:5], "Amadeus"

def motor_serpapi():
    k = os.getenv("SERPAPI_KEY", "").strip()
    if not k:
        raise RuntimeError("sem chave")
    params = {"engine": "google_flights", "departure_id": ORIGEM, "arrival_id": DESTINO,
              "outbound_date": DATA_IDA, "currency": "EUR", "adults": PAX, "hl": "pt", "api_key": k}
    if DATA_VOLTA:
        params["return_date"] = DATA_VOLTA
    else:
        params["type"] = "2"
    r = requests.get("https://serpapi.com/search.json", params=params, timeout=55).json()
    if "error" in r:
        raise RuntimeError(str(r["error"])[:100])
    voos = (r.get("best_flights") or []) + (r.get("other_flights") or [])
    saida = []
    for v in voos:
        try:
            pernas = v.get("flights") or []
            saida.append({
                "companhia": pernas[0].get("airline", "?"), "preco": round(float(v["price"])),
                "escalas": "Direto" if len(pernas) == 1 else f"{len(pernas)-1} escala(s)",
                "hora": (pernas[0].get("departure_airport", {}).get("time", "") or "")[-5:],
            })
        except Exception:
            continue
    if not saida:
        raise RuntimeError("0 voos")
    return sorted(saida, key=lambda x: x["preco"])[:5], "SerpAPI · Google Flights"

def motor_travelpayouts():
    t = os.getenv("TP_TOKEN", "").strip()
    if not t:
        raise RuntimeError("sem token")
    params = {"origin": ORIGEM, "destination": DESTINO, "currency": "EUR",
              "depart_date": DATA_IDA[:7], "token": t}
    if DATA_VOLTA:
        params["return_date"] = DATA_VOLTA[:7]
    r = requests.get("https://api.travelpayouts.com/v1/prices/cheap", params=params, timeout=25).json()
    dados = (r.get("data") or {}).get(DESTINO, {})
    saida = []
    for _, v in list(dados.items())[:10]:
        p = round(float(v.get("price", 0)))
        if p > 0:
            cia = v.get("airline", "?")
            part = v.get("departure_at", "")
            saida.append({"companhia": NOMES.get(cia, cia), "preco": p,
                          "escalas": "ver no link", "hora": part[11:16] if len(part) >= 16 else ""})
    if not saida:
        raise RuntimeError("cache vazia")
    return sorted(saida, key=lambda x: x["preco"])[:5], "Travelpayouts"

def telegram(msg):
    tok, chat = os.getenv("TELEGRAM_TOKEN", "").strip(), os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not tok or not chat:
        print("[aviso] Telegram não configurado")
        return
    requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
        json={"chat_id": chat, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=15)

def discord(msg_plano):
    url = os.getenv("DISCORD_WEBHOOK", "").strip()
    if not url:
        return
    try:
        requests.post(url, json={"content": msg_plano[:1900]}, timeout=15)
    except Exception as e:
        print("[aviso] Discord falhou:", e)

def whatsapp_proprio(msg_plano):
    """Alerta no TEU WhatsApp via CallMeBot (grátis): segue as instruções do LEIA-ME."""
    fone = os.getenv("WHATSAPP_PHONE", "").strip()
    chave = os.getenv("CALLMEBOT_APIKEY", "").strip()
    if not fone or not chave:
        return
    try:
        requests.get("https://api.callmebot.com/whatsapp.php",
                     params={"phone": fone, "text": msg_plano[:900], "apikey": chave}, timeout=20)
    except Exception as e:
        print("[aviso] WhatsApp/CallMeBot falhou:", e)

def escrever_rss(titulo, descricao, link):
    """Publica a promoção em feed.xml — ponte para LinkedIn/Facebook/X via dlvr.it ou Zapier."""
    import html
    try:
        with open("feed_itens.json", encoding="utf-8") as f:
            itens = json.load(f)
    except Exception:
        itens = []
    itens = ([{"titulo": titulo, "descricao": descricao, "link": link,
               "quando": time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())}] + itens)[:20]
    with open("feed_itens.json", "w", encoding="utf-8") as f:
        json.dump(itens, f, ensure_ascii=False, indent=1)
    corpo = "".join(
        f"<item><title>{html.escape(i['titulo'])}</title>"
        f"<description>{html.escape(i['descricao'])}</description>"
        f"<link>{html.escape(i['link'])}</link>"
        f"<pubDate>{i['quando']}</pubDate>"
        f"<guid isPermaLink=\"false\">{html.escape(i['quando'] + i['titulo'])}</guid></item>"
        for i in itens
    )
    with open("feed.xml", "w", encoding="utf-8") as f:
        f.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?><rss version=\"2.0\"><channel>"
                "<title>Radar de Voos — Promoções</title>"
                "<link>https://www.aviasales.pt/</link>"
                "<description>Alertas de voos baratos encontrados pelo radar</description>"
                + corpo + "</channel></rss>")

def enviar_todos(msg_html, msg_plano, titulo, link):
    telegram(msg_html)
    discord(msg_plano)
    whatsapp_proprio(msg_plano)
    escrever_rss(titulo, msg_plano, link)

def principal():
    global ORIGEM, DESTINO, DATA_IDA, DATA_VOLTA, ALVO
    rotas = carregar_rotas()
    idx = int(time.strftime("%H")) % len(rotas)   # rotação: cada hora, uma rota
    r = rotas[idx]
    ORIGEM, DESTINO, DATA_IDA, DATA_VOLTA, ALVO = r["origem"], r["destino"], r["ida"], r["volta"], r["alvo"]
    print(f"Rota desta hora ({idx+1}/{len(rotas)}): {ORIGEM}→{DESTINO} · alvo €{ALVO:.0f}")
    resultados, fonte, erros = None, "", []
    for motor in (motor_amadeus, motor_serpapi, motor_travelpayouts):
        try:
            resultados, fonte = motor()
            break
        except Exception as e:
            erros.append(f"{motor.__name__}: {e}")
    if resultados is None:
        print("Nenhum motor respondeu:", " | ".join(erros))
        telegram("⚠️ Radar: nenhum motor respondeu nesta hora.\n" + "\n".join(erros)[:500])  # só Telegram, para não poluir os canais públicos
        return

    melhor = resultados[0]
    # histórico
    try:
        with open("precos.json", encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        hist = {"rotas": {}, "verificacoes": []}
    if "rotas" not in hist:
        hist = {"rotas": ({f"{ORIGEM}-{DESTINO}": {"minimo": hist.get("minimo")}} if hist.get("minimo") else {}),
                "verificacoes": hist.get("verificacoes", [])}
    chave_rota = f"{ORIGEM}-{DESTINO}"
    rota_hist = hist["rotas"].setdefault(chave_rota, {"minimo": None})
    min_anterior = rota_hist.get("minimo")
    agora = time.strftime("%Y-%m-%d %H:%M")
    hist["verificacoes"] = (hist.get("verificacoes") or [])[-500:] + [
        {"quando": agora, "rota": chave_rota, "fonte": fonte, "melhor": melhor["preco"], "companhia": melhor["companhia"]}
    ]

    bate_alvo = melhor["preco"] <= ALVO
    bate_minimo = min_anterior is not None and melhor["preco"] < min_anterior
    if min_anterior is None or melhor["preco"] < min_anterior:
        rota_hist["minimo"] = melhor["preco"]

    with open("precos.json", "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=1)

    print(f"[{agora}] {chave_rota} · {fonte} → melhor €{melhor['preco']} ({melhor['companhia']}) · mínimo da rota €{rota_hist['minimo']}")

    if bate_alvo or bate_minimo:
        motivo = f"no alvo (≤ €{ALVO:.0f})" if bate_alvo else f"abaixo do mínimo anterior (€{min_anterior})"
        linhas = "\n".join(
            f"• <b>€{x['preco']}</b> — {x['companhia']} · {x['escalas']}" + (f" · {x['hora']}" if x['hora'] else "")
            for x in resultados
        )
        rota_txt = f"{ORIGEM} → {DESTINO} · {DATA_IDA}" + (f" ↩ {DATA_VOLTA}" if DATA_VOLTA else "") + f" · {PAX} pax"
        msg_html = (f"🔔 <b>ALERTA DE PREÇO</b> — {motivo}\n✈️ {rota_txt}\n\n{linhas}\n\n"
                    f"👉 Reservar: {link_afiliado()}\nfonte: {fonte} · {agora}")
        linhas_plano = "\n".join(
            f"- €{x['preco']} — {x['companhia']} · {x['escalas']}" + (f" · {x['hora']}" if x['hora'] else "")
            for x in resultados)
        msg_plano = (f"🔔 ALERTA DE PREÇO — {motivo}\n✈️ {rota_txt}\n\n{linhas_plano}\n\n"
                     f"Reservar: {link_afiliado()}")
        titulo = f"✈️ {ORIGEM}→{DESTINO} desde €{melhor['preco']} — {melhor['companhia']}"
        enviar_todos(msg_html, msg_plano, titulo, link_afiliado())

if __name__ == "__main__":
    principal()
