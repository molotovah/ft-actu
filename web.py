"""Web UI. Authentication is done in front by Authelia (2FA), except /confirm,
which is bypassed there and protected by its single-use token."""
import html
import json
import os
import re
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import app as bot
import auth
from app import QUESTIONS, d, state

FT_ACTU = "https://candidat.francetravail.fr/espacepersonnel/"
e = html.escape

CSS = """
:root{--bg:#f4f6fb;--card:#fff;--text:#1b2233;--muted:#667085;--line:#e4e8f0;--accent:#2f5bea;
--accent-ink:#fff;--ok:#12805c;--ok-bg:#e3f6ee;--warn:#a15c00;--warn-bg:#fff3dc;--bad:#c0362c;
--bad-bg:#fde8e6;--chip:#eef2ff;--shadow:0 1px 2px rgba(16,24,40,.06),0 4px 16px rgba(16,24,40,.06)}
@media (prefers-color-scheme:dark){:root{--bg:#0f131c;--card:#171c28;--text:#e6e9f0;--muted:#98a2b3;
--line:#262d3d;--accent:#7c9cff;--accent-ink:#0f131c;--ok:#4cd39b;--ok-bg:#12352a;--warn:#ffc061;
--warn-bg:#3a2b10;--bad:#ff8a80;--bad-bg:#3d1c1a;--chip:#222a3d;--shadow:none}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1040px;margin:0 auto;padding:24px 16px 48px}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;margin-bottom:20px}
h1{font-size:22px;margin:0}h2{font-size:16px;margin:0 0 14px}
.sub{color:var(--muted);font-size:13px}
.grid{display:grid;gap:16px;grid-template-columns:repeat(12,minmax(0,1fr))}.grid>*{grid-column:span 12}
@media (min-width:860px){.s7{grid-column:span 7}.s5{grid-column:span 5}}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;box-shadow:var(--shadow)}
.pill{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:999px;font-weight:600;font-size:14px}
.pill.ok{background:var(--ok-bg);color:var(--ok)}.pill.warn{background:var(--warn-bg);color:var(--warn)}
.pill.bad{background:var(--bad-bg);color:var(--bad)}.pill.idle{background:var(--chip);color:var(--muted)}
.big{font-size:40px;font-weight:700;line-height:1.1;margin:10px 0 2px}
.kv{display:grid;grid-template-columns:auto 1fr;gap:6px 16px;margin:0}.kv dt{color:var(--muted)}.kv dd{margin:0;font-weight:500}
.bar{position:relative;height:8px;background:var(--chip);border-radius:99px;margin:18px 0 6px}
.bar i{position:absolute;inset:0 auto 0 0;background:var(--accent);border-radius:99px}
.bar-l{display:flex;justify-content:space-between;color:var(--muted);font-size:12px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;border:1px solid var(--line);background:var(--card);
color:var(--text);padding:9px 16px;border-radius:10px;font:inherit;font-weight:600;cursor:pointer;text-decoration:none}
.btn:hover{border-color:var(--accent)}.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.btn.primary:hover{filter:brightness(1.08)}.btn[disabled]{opacity:.5;cursor:not-allowed}
.btn.lg{padding:14px 22px;font-size:17px;width:100%}
.q{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;justify-content:space-between;padding:12px 0;border-top:1px solid var(--line)}
.q:first-of-type{border-top:0}.q p{margin:0;flex:1 1 260px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.seg input{position:absolute;opacity:0;pointer-events:none}
.seg label{padding:7px 18px;cursor:pointer;font-weight:600;color:var(--muted)}
.seg input:checked+label{background:var(--accent);color:var(--accent-ink)}
.seg input:focus-visible+label{outline:2px solid var(--accent);outline-offset:-2px}
.seg.fixed label{cursor:default}
.actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:16px}
.note{border-radius:10px;padding:12px 14px;margin:12px 0;font-size:14px}
.note.warn{background:var(--warn-bg);color:var(--warn)}.note.ok{background:var(--ok-bg);color:var(--ok)}
.note.bad{background:var(--bad-bg);color:var(--bad)}.note.info{background:var(--chip)}
.note a{color:inherit;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--line);white-space:nowrap}th{color:var(--muted);font-weight:500}
tr.cur td{font-weight:700;background:var(--chip)}tr.past td{color:var(--muted)}
.tw{overflow-x:auto}
.ev{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;padding:12px 0;border-top:1px solid var(--line)}
.ev:first-child{border-top:0}.ev time{color:var(--muted);font-size:13px;white-space:nowrap}
details summary{cursor:pointer;color:var(--muted);font-size:13px}
pre{white-space:pre-wrap;font-size:12px;background:var(--chip);padding:10px;border-radius:8px;overflow:auto}
.thumbs{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
.thumbs a img{width:120px;height:80px;object-fit:cover;object-position:top;border-radius:8px;border:1px solid var(--line)}
.lb{display:none;position:fixed;inset:0;background:rgba(0,0,0,.8);z-index:9;padding:24px;overflow:auto}
.lb:target{display:block}.lb img{display:block;max-width:100%;margin:0 auto;border-radius:8px}
.lb a.x{position:fixed;top:12px;right:20px;color:#fff;font-size:30px;text-decoration:none}
.flash{position:sticky;top:12px;z-index:5;margin-bottom:16px}
.center{max-width:560px;margin:0 auto}
nav{display:flex;flex-wrap:wrap;gap:8px}
nav a.on{background:var(--chip);border-color:var(--chip)}
.field{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;justify-content:space-between;padding:12px 0;border-top:1px solid var(--line)}
.field:first-of-type{border-top:0}.field>div{flex:1 1 240px}.field small{display:block;color:var(--muted);font-size:13px}
input[type=number],input[type=email],input[type=text],input[type=url],input[type=password]{font:inherit;color:var(--text);background:var(--bg);
border:1px solid var(--line);border-radius:10px;padding:8px 12px}
input[type=number]{width:84px}input[type=email],input[type=text],input[type=url],input[type=password]{width:min(100%,320px)}
.center .field>div{flex-basis:100%}.center input[type=password],.center input[type=text]{width:100%}
.tl{list-style:none;margin:0;padding:0}.tl li{position:relative;padding:0 0 14px 26px}
.tl li:before{content:"";position:absolute;left:5px;top:6px;width:10px;height:10px;border-radius:50%;
background:var(--card);border:2px solid var(--line)}
.tl li:after{content:"";position:absolute;left:10px;top:20px;bottom:-2px;width:2px;background:var(--line)}
.tl li:last-child:after{display:none}.tl li.done:before{background:var(--ok);border-color:var(--ok)}
.tl li.now:before{background:var(--accent);border-color:var(--accent);box-shadow:0 0 0 4px var(--chip)}
.tl b{display:block;font-weight:600}.tl span{color:var(--muted);font-size:13px}
.empty{color:var(--muted);margin:14px 0}
input:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.range{display:inline-flex;align-items:center;gap:8px}
.switch{position:relative;display:inline-block;width:46px;height:26px;flex:none}
.switch input{opacity:0;width:0;height:0}
.switch span{position:absolute;inset:0;background:var(--line);border-radius:99px;cursor:pointer;transition:.15s}
.switch span:before{content:"";position:absolute;width:20px;height:20px;left:3px;top:3px;background:#fff;border-radius:50%;transition:.15s}
.switch input:checked+span{background:var(--accent)}.switch input:checked+span:before{transform:translateX(20px)}
.switch input:focus-visible+span{outline:2px solid var(--accent);outline-offset:2px}
.btn.danger{color:var(--bad)}
"""


FAVICON = ("<link rel=icon href=\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
           "%3Crect width='32' height='32' rx='8' fill='%232f5bea'/%3E%3Cpath d='M9 16.5l4.5 4.5L23 11.5' "
           "stroke='white' stroke-width='3.5' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E\">")


def page(title, body, refresh=False):
    meta = "<meta http-equiv=refresh content=10>" if refresh else ""
    return (f"<!doctype html><html lang=fr><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>{meta}{FAVICON}"
            f"<title>{e(title)}</title><style>{CSS}</style><body><main>{body}</main>")


def status_pill():
    if state.get("running"):
        return "<span class='pill warn'>⏳ Actualisation en cours…</span>"
    s = re.sub(r"\s*J\s*[−-]\s*\d+$", "", state.get("status") or "En attente de la 1re vérification")
    cls = "ok" if "valid" in s.lower() else "warn" if "effectuer" in s.lower() else "idle"
    return f"<span class='pill {cls}'>{e(s)}</span>"


def fmt_iso(iso):
    return datetime.fromisoformat(iso).strftime("%d/%m à %Hh%M") if iso else "—"


def next_period(now):
    return next((p for p in state.get("calendar") or [] if d(p["ouverture"]) > now), None)


def card_status(now):
    period = bot.current_period(now)
    deadline = state.get("deadline")
    if deadline and "effectuer" in (state.get("status") or "").lower():
        days = (d(deadline) - now.replace(hour=0, minute=0, second=0, microsecond=0)).days
        big = f"<div class=big>J−{days}</div><div class=sub>avant la clôture du {deadline}</div>"
    elif (nxt := next_period(now)):
        big = (f"<div class=big>{(d(nxt['ouverture']) - now).days + 1} j</div>"
               f"<div class=sub>avant l'ouverture du {nxt['ouverture']} ({e(nxt['mois'])})</div>")
    elif not state.get("checked_at"):
        big = "<p class=empty>Le bot ne s'est pas encore connecté. Lance une vérification pour récupérer ton statut et le calendrier.</p>"
    else:
        big = ""
    bar = ""
    if period:
        start, end = d(period["ouverture"]), d(period["cloture"]) + timedelta(days=1)
        pct = max(0, min(100, (now - start) / (end - start) * 100))
        bar = (f"<div class=bar><i style='width:{pct:.0f}%'></i></div><div class=bar-l>"
               f"<span>Ouverture {period['ouverture']}</span><span>Clôture {period['cloture']}</span></div>")
    pay = period or next_period(now)
    return f"""<section class='card s7'><h2>Statut</h2>{status_pill()}{big}{bar}
<dl class=kv style='margin-top:16px'>
<dt>Période</dt><dd>{e(period['mois']) if period else 'hors période'}</dd>
<dt>Virement à partir du</dt><dd>{pay['virement'] if pay else '—'}</dd>
<dt>Dernière vérification</dt><dd>{e(state.get('checked_at') or '—')}</dd></dl>
<form method=post action=/check class=actions><button class=btn>↻ Vérifier maintenant</button></form></section>"""


def card_plan(now):
    plan, p, cfg = state.get("plan") or {}, state.get("pending"), bot.settings()
    period = bot.current_period(now)
    nxt = period or next_period(now)
    done = bool(period and state.get("handled") == period["cloture"]) or "valid" in (state.get("status") or "").lower()
    steps = []  # (state, title, detail)
    if nxt:
        steps.append(("done" if period else "now", f"Ouverture · {e(nxt['mois'])}", nxt["ouverture"]))
        if done:
            steps.append(("done", "Actualisation validée", e(state.get("status") or "")))
        else:
            if p:
                steps.append(("done", "Demande envoyée", "en attente de ta réponse"))
            else:
                steps.append(("now" if period else "", "Demande de confirmation",
                              fmt_iso(plan.get("request_at")) if period and plan.get("cloture") == period["cloture"]
                              else f"dans les {cfg['request_days']} premiers jours"))
            if p and p.get("auto_at") and cfg["auto"] and bot.auto_ok():
                steps.append(("now", "Actualisation automatique", fmt_iso(p["auto_at"])))
            else:
                steps.append(("now" if p else "", "Ta validation", "par e-mail, ntfy ou ici"))
        steps.append(("", "Virement à partir du", nxt["virement"]))
        if not done:
            steps.append(("", "Rappel si besoin", f"{cfg['remind_days']} jours avant la clôture"))
        steps.append(("done" if done else "", "Clôture", nxt["cloture"]))
    items = "".join(f"<li class='{c}'><b>{t}</b><span>{dt}</span></li>" for c, t, dt in steps)
    mode = "⏸ en pause" if cfg["paused"] else "automatique" if cfg["auto"] else "avec confirmation"
    return f"""<section class='card s5'><h2>Planning</h2><ol class=tl>{items or "<li>Calendrier pas encore chargé.</li>"}</ol>
<dl class=kv><dt>Mode</dt><dd>{mode}</dd><dt>Prochaine vérification</dt><dd>{fmt_iso(state.get('next_check'))}</dd></dl>
<p class=sub style='margin-bottom:0'>Horaires tirés au hasard ({cfg['check_start']}h–{cfg['check_end']}h) pour
ne pas agir à heure fixe.</p></section>"""


def seg(name, value, fixed=False):
    if fixed:
        return "<span class='seg fixed'><input type=radio checked disabled><label>Oui</label></span>"
    out = []
    for v, label in (("oui", "Oui"), ("non", "Non")):
        checked = " checked" if (v == "oui") == value else ""
        out.append(f"<input type=radio id={name}-{v} name={name} value={v}{checked}><label for={name}-{v}>{label}</label>")
    return f"<span class=seg>{''.join(out)}</span>"


def card_month():
    todo = "effectuer" in (state.get("status") or "").lower()
    if not todo:
        msg = ("Actualisation du mois validée. Les réponses du prochain mois seront modifiables à l'ouverture."
               if "valid" in (state.get("status") or "").lower() else "Aucune actualisation ouverte.")
        return f"<section class=card id=mois><h2>Mois en cours</h2><div class='note ok'>{msg}</div></section>"
    a = bot.answers()
    rows = "".join(f"<div class=q><p>{e(q)}</p>{seg(k, a[k])}</div>" for k, q in QUESTIONS.items())
    rows += f"<div class=q><p>Souhaitez-vous rester inscrit à France Travail ?</p>{seg('inscrit', True, True)}</div>"
    running = state.get("running")
    if bot.auto_ok():
        note = ("<div class='note info'>Ces réponses sont déclarées <b>sur l'honneur</b>. Vérifie-les avant "
                "de valider.</div>")
        go = f"<button class='btn primary' name=go value=1{' disabled' if running else ''}>✓ Enregistrer et actualiser</button>"
    else:
        note = ("<div class='note warn'>Une réponse est <b>Oui</b> : il faut détailler les périodes "
                f"(contrats, dates, heures, montants). Le bot ne le fait pas : <a href='{FT_ACTU}' target=_blank "
                "rel=noopener>actualise-toi sur francetravail.fr</a>.</div>")
        go = ""
    return f"""<section class=card id=mois><h2>Mois en cours · échéance {state['deadline']}</h2>
<form method=post action=/answers>{rows}{note}<div class=actions>
<button class=btn name=go value=0>Enregistrer</button>{go}</div></form></section>"""


def card_calendar(now):
    cur = bot.current_period(now)
    rows = []
    for p in state.get("calendar") or []:
        if d(p["cloture"]) < now - timedelta(days=62):
            continue
        cls = "cur" if p == cur else "past" if d(p["cloture"]) < now else ""
        rows.append(f"<tr class='{cls}'><td>{e(p['mois'])}</td><td>{p['ouverture']}</td>"
                    f"<td>{p['virement']}</td><td>{p['cloture']}</td></tr>")
    return f"""<section class='card s7'><h2>Calendrier</h2><div class=tw><table>
<tr><th>Allocation</th><th>Ouverture</th><th>Virement</th><th>Clôture</th></tr>{''.join(rows)}</table></div></section>"""


RESULT_CLS = {"actualisation validée": "ok", "erreur": "bad", "refusée": "idle"}


def card_history():
    evs, boxes = [], []
    for h in state.get("history", [])[:30]:
        thumbs = ""
        for s in h["shots"]:
            sid = s.rsplit(".", 1)[0]
            thumbs += f"<a href='#{sid}'><img src='/shots/{s}' alt='{e(s.split('-', 2)[2])}' loading=lazy></a>"
            boxes.append(f"<div class=lb id={sid}><a class=x href='#hist'>×</a><img src='/shots/{s}' alt=''></div>")
        detail = f"<details><summary>Détail</summary><pre>{e(h['detail'])}</pre></details>" if h["detail"] else ""
        evs.append(f"<div class=ev><time>{h['at']}</time><div><span class='pill {RESULT_CLS.get(h['result'], 'idle')}'>"
                   f"{e(h['result'])}</span>{detail}<div class=thumbs>{thumbs}</div></div></div>")
    body = "".join(evs) or "<p class=sub>Rien pour l'instant.</p>"
    return f"<section class='card s5' id=hist><h2>Historique</h2>{body}</section>{''.join(boxes)}"


FLASH = {"saved": ("ok", "Réponses enregistrées."), "started": ("ok", "Actualisation lancée, résultat dans quelques minutes."),
         "check": ("info", "Vérification lancée, rafraîchis dans une minute."),
         "busy": ("warn", "Une actualisation est déjà en cours."),
         "manual": ("warn", "Réponses enregistrées. Une réponse est Oui : actualise-toi sur francetravail.fr."),
         "settings": ("ok", "Réglages enregistrés."), "invalid": ("bad", "Valeur invalide, réglages non enregistrés."),
         "notif": ("info", "Notification de test envoyée."), "notif-ko": ("bad", "Échec de la notification de test (voir historique)."),
         "login": ("info", "Test de connexion lancé, résultat dans l'historique d'ici une minute."),
         "profile": ("ok", "Profil navigateur réinitialisé : la prochaine connexion demandera un code e-mail."),
         "totp-on": ("ok", "Double authentification activée."), "totp-off": ("warn", "Double authentification désactivée."),
         "pk-added": ("ok", "Passkey ajoutée."), "pk-deleted": ("ok", "Passkey supprimée."),
         "others": ("ok", "Les autres appareils sont déconnectés.")}


def mask(s):
    return s[:2] + "•" * max(len(s) - 4, 3) + s[-2:] if len(s) > 4 else "•••"


def header(active):
    links = [("/", "Tableau de bord"), ("/reglages", "Réglages")] + ([("/securite", "Sécurité")] if AUTH_MODE == "builtin" else [])
    nav = "".join(f"<a class='btn{' on' if href == active else ''}' href='{href}'>{label}</a>" for href, label in links)
    return (f"<header><div><h1>Actualisation France Travail</h1><div class=sub>Identifiant {e(mask(bot.FT_ID))}</div></div>"
            f"<nav>{nav}<a class=btn href='{FT_ACTU}' target=_blank rel=noopener>France Travail ↗</a></nav></header>")


def flash_note(msg):
    if msg not in FLASH:
        return ""
    cls, text = FLASH[msg]
    return f"<div class='note {cls} flash'>{text}</div>"


def dashboard(msg):
    now = datetime.now()
    paused = ("<div class='note warn'>⏸ Le bot est <b>en pause</b> : aucune vérification ni demande. "
              "<a href='/reglages'>Réglages</a></div>" if bot.settings()["paused"] else "")
    db = auth.load() if AUTH_MODE == "builtin" else {}
    if AUTH_MODE == "builtin" and not db.get("totp") and not db.get("passkeys"):
        paused += ("<div class='note warn'>🔓 Ton accès n'est protégé que par un mot de passe. "
                   "<a href='/securite'>Active la double authentification ou une passkey</a>.</div>")
    body = f"""{header("/")}{flash_note(msg)}{paused}
<div class=grid>{card_status(now)}{card_plan(now)}{card_month()}{card_calendar(now)}{card_history()}</div>"""
    return page("Actualisation France Travail", body, refresh=bool(state.get("running")))


def switch(name, on):
    return (f"<label class=switch><input type=checkbox name={name} value=1{' checked' if on else ''} "
            f"aria-label='{name}'><span></span></label>")


def field(title, hint, control):
    return f"<div class=field><div><b>{title}</b><small>{hint}</small></div>{control}</div>"


def num(name, value, lo, hi, label):
    return f"<input type=number name={name} value={value} min={lo} max={hi} required aria-label='{label}'>"


def settings_page(msg):
    c = bot.settings()
    defaults = "".join(f"<div class=q><p>{e(q)}</p>{seg('def-' + k, c['defaults'][k])}</div>" for k, q in QUESTIONS.items())
    ntfy_ok = "" if bot.NTFY_TOKEN else "<small>Sans NTFY_TOKEN dans le .env : topic public, choisis un nom difficile à deviner.</small>"
    body = f"""{header("/reglages")}{flash_note(msg)}
<form method=post action=/reglages class=grid style='align-items:start'>
<section class='card s7'><h2>Bot</h2>
{field("Pause", "Aucune vérification, demande ni actualisation tant que la pause est active.", switch("paused", c["paused"]))}
{field("Plage horaire", "Les vérifications et demandes tombent au hasard dans cette plage.",
       f"<span class=range>{num('check_start', c['check_start'], 0, 23, 'Heure de début')} h à {num('check_end', c['check_end'], 1, 23, 'Heure de fin')} h</span>")}
{field("Délai de la demande", "La demande part au hasard dans les N premiers jours de la période.",
       f"<span class=range>{num('request_days', c['request_days'], 1, 10, 'Jours')} jours</span>")}
{field("Rappel", "Si tu n'as pas répondu, rappel N jours avant la clôture.",
       f"<span class=range>{num('remind_days', c['remind_days'], 1, 14, 'Jours')} jours</span>")}
</section>
<section class='card s5'><h2>Notifications</h2>
{field("E-mail", "Adresse qui reçoit demandes, rappels et résultats.",
       f"<input type=email name=notify_email value='{e(c['notify_email'])}' required>")}
{field("ntfy", "Notification push en plus de l'e-mail." + ntfy_ok, switch("ntfy", c["ntfy"]))}
{field("Serveur ntfy", "", f"<input type=url name=ntfy_server value='{e(c['ntfy_server'])}'>")}
{field("Topic", "", f"<input type=text name=ntfy_topic value='{e(c['ntfy_topic'])}' pattern='[A-Za-z0-9_-]+'>")}
</section>
<section class='card s7'><h2>Mode d'actualisation</h2>
{field("Actualisation automatique", "Sans confirmation, seulement si toutes les réponses sont Non. "
       "Tu reçois un avis avec un bouton Modifier avant l'envoi.", switch("auto", c["auto"]))}
{field("Délai avant envoi auto", "Temps laissé pour modifier ou annuler après l'avis.",
       f"<span class=range>{num('auto_delay_h', c['auto_delay_h'], 1, 168, 'Heures')} h</span>")}
</section>
<section class='card s5'><h2>Réponses par défaut</h2>
<p class=sub style='margin-top:0'>Point de départ de chaque nouveau mois (ex. formation longue).</p>{defaults}</section>
<div class=actions style='grid-column:1/-1'><button class='btn primary'>Enregistrer les réglages</button></div>
</form>
<div class=grid style='margin-top:16px'><section class=card><h2>Maintenance</h2>
<div class=actions style='margin-top:0'>
<form method=post action=/test-login><button class=btn>🔑 Tester la connexion</button></form>
<form method=post action=/test-notif><button class=btn>🔔 Tester les notifications</button></form>
<form method=post action=/reset-profile><button class='btn danger'>↺ Réinitialiser le profil navigateur</button></form>
</div><p class=sub style='margin-bottom:0'>Identifiants France Travail et Gmail : dans <code>.env</code> sur le serveur,
jamais dans l'interface.</p></section></div>"""
    return page("Réglages · Actualisation", body)


def parse_settings(form):
    c = bot.settings()
    c["paused"], c["auto"], c["ntfy"] = (form.get(k) == "1" for k in ("paused", "auto", "ntfy"))
    for k in ("check_start", "check_end", "request_days", "remind_days", "auto_delay_h"):
        c[k] = int(form[k])
    c["notify_email"] = form["notify_email"].strip()
    c["ntfy_server"] = form.get("ntfy_server", "").strip().rstrip("/")
    c["ntfy_topic"] = form.get("ntfy_topic", "").strip()
    c["defaults"] = {k: form.get("def-" + k) == "oui" for k in QUESTIONS}
    ok = (0 <= c["check_start"] < c["check_end"] <= 23 and 1 <= c["request_days"] <= 10
          and 1 <= c["remind_days"] <= 14 and 1 <= c["auto_delay_h"] <= 168
          and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", c["notify_email"])
          and re.fullmatch(r"[A-Za-z0-9_-]*", c["ntfy_topic"])
          and (not c["ntfy"] or (c["ntfy_server"].startswith("http") and c["ntfy_topic"])))
    if not ok:
        raise ValueError
    return c


def confirm_page(token):
    rows = "".join(f"<div class=q><p>{e(q)}</p><b>{r}</b></div>" for q, r in bot.answer_lines())
    if bot.auto_ok():
        action = (f"<form method=post><input type=hidden name=t value='{e(token)}'>"
                  "<button class='btn primary lg' name=action value=ok autofocus>✓ Confirmer et actualiser</button></form>")
    else:
        action = (f"<div class='note warn'>Une réponse est Oui : <a href='{FT_ACTU}'>actualise-toi sur "
                  "francetravail.fr</a>.</div>")
    p = state["pending"]
    auto = (f"<div class='note info'>Sans action de ta part, l'actualisation sera faite automatiquement le "
            f"{fmt_iso(p['auto_at'])}.</div>" if p.get("auto_at") and bot.settings()["auto"] else "")
    body = f"""<div class=center><section class=card><h2>Actualisation · échéance {p['deadline']}</h2>
{rows}{auto}<div class='note info'>Déclaration <b>sur l'honneur</b>.</div>{action}
<div class=actions><a class='btn lg' href='{bot.BASE_URL}/#mois'>✎ Modifier les réponses</a></div></section></div>"""
    return page("Confirmer l'actualisation", body)


def notice_page(title, text, cls="info"):
    return page(title, f"<div class=center><section class=card><h2>{e(title)}</h2>"
                       f"<div class='note {cls}'>{text}</div><div class=actions>"
                       f"<a class=btn href='{bot.BASE_URL}/'>Tableau de bord</a></div></section></div>")


def request_mail(deadline, lines, ok_url, edit_url, ok, auto_at=None):
    """HTML e-mail: inline styles and tables only (mail clients)."""
    rows = "".join(f"<tr><td style='padding:8px 0;border-top:1px solid #e4e8f0;color:#1b2233'>{e(q)}</td>"
                   f"<td style='padding:8px 0 8px 16px;border-top:1px solid #e4e8f0;font-weight:700;text-align:right'>{r}</td></tr>"
                   for q, r in lines)
    btn = ("display:inline-block;padding:13px 22px;border-radius:10px;font-weight:700;"
           "font-family:system-ui,sans-serif;text-decoration:none;font-size:16px;margin:4px 6px 4px 0")
    ok_btn = (f"<a href='{ok_url}' style='{btn};background:#2f5bea;color:#fff'>✓ OK, actualiser</a>" if ok else
              "<p style='color:#a15c00'>Une réponse est Oui : actualisation à faire sur francetravail.fr.</p>")
    return f"""<div style='background:#f4f6fb;padding:24px 12px;font-family:system-ui,-apple-system,sans-serif'>
<table role=presentation style='max-width:560px;margin:0 auto;background:#fff;border-radius:14px;padding:24px;border:1px solid #e4e8f0' width=100%>
<tr><td><h1 style='font-size:20px;margin:0 0 4px;color:#1b2233'>Actualisation France Travail</h1>
<p style='margin:0 0 16px;color:#667085'>{f"Actualisation <b>automatique le {auto_at}</b>, sauf si tu modifies." if auto_at
    else f"À faire avant le <b>{deadline}</b>."} Réponses prévues :</p>
<table role=presentation width=100% style='font-size:14px;border-collapse:collapse'>{rows}</table>
<p style='margin:20px 0 8px'>{ok_btn}<a href='{edit_url}' style='{btn};background:#eef2ff;color:#2f5bea'>✎ Modifier</a></p>
<p style='color:#667085;font-size:12px;margin:12px 0 0'>Déclaration sur l'honneur. « OK » ouvre une page de confirmation
en un clic.</p></td></tr></table></div>"""


def auth_page(title, inner):
    return page(title, f"<div class=center style='margin-top:8vh'><section class=card><h1 style='margin-bottom:4px'>"
                       f"Actualisation France Travail</h1><p class=sub style='margin-top:0'>{e(title)}</p>{inner}"
                       "</section></div><script src=/static/passkey.js></script>")


def error_note(msg):
    return f"<div class='note bad'>{e(msg)}</div>" if msg else ""


def setup_page(token, err=""):
    return auth_page("Première configuration", f"""{error_note(err)}
<p>Choisis le mot de passe de l'interface ({auth.MIN_PASSWORD} caractères minimum). Tu pourras ensuite
activer la double authentification et ajouter une passkey.</p>
<form method=post action=/setup><input type=hidden name=token value='{e(token)}'>
<div class=field><div><b>Mot de passe</b></div><input type=password name=password autocomplete=new-password required minlength={auth.MIN_PASSWORD}></div>
<div class=field><div><b>Confirmation</b></div><input type=password name=confirm autocomplete=new-password required></div>
<div class=actions><button class='btn primary lg'>Créer l'accès</button></div></form>""")


def login_page(err=""):
    pk = auth.load()["passkeys"]
    passkey = ("<div class=actions><button class='btn lg' data-passkey=login>🔑 Se connecter avec une passkey</button></div>"
               "<p class=sub style='text-align:center'>ou</p>" if pk else "")
    return auth_page("Connexion", f"""{error_note(err)}<div id=pk-msg class='note bad' hidden></div>{passkey}
<form method=post action=/login>
<div class=field><div><b>Mot de passe</b></div><input type=password name=password autocomplete=current-password required autofocus></div>
<div class=actions><button class='btn primary lg'>Continuer</button></div></form>""")


def totp_login_page(err=""):
    return auth_page("Double authentification", f"""{error_note(err)}
<form method=post action=/login/totp><p>Code à 6 chiffres de ton application d'authentification.</p>
<div class=field><div><b>Code</b></div><input type=text name=code inputmode=numeric autocomplete=one-time-code
pattern='[0-9 ]{{6,7}}' required autofocus style='width:140px;letter-spacing:.2em'></div>
<div class=actions><button class='btn primary lg'>Valider</button></div></form>""")


def security_page(msg, err="", totp_secret=None):
    db = auth.load()
    if totp_secret:
        totp = f"""<p>Scanne ce QR code avec ton application (Aegis, 2FAS, Google Authenticator, Bitwarden…),
puis saisis le code affiché.</p><div style='background:#fff;display:inline-block;padding:8px;border-radius:10px'>
{auth.totp_qr_svg(totp_secret)}</div><p class=sub>Clé manuelle : <code>{totp_secret}</code></p>
<form method=post action=/totp/confirm class=actions><input type=text name=code inputmode=numeric
autocomplete=one-time-code required placeholder='123456' style='width:140px'><button class='btn primary'>Activer</button></form>"""
    elif db.get("totp"):
        totp = """<div class='note ok'>Double authentification <b>active</b>.</div>
<form method=post action=/totp/disable class=actions><input type=password name=password placeholder='Mot de passe'
autocomplete=current-password required><button class='btn danger'>Désactiver</button></form>"""
    else:
        totp = """<div class='note warn'>Double authentification <b>inactive</b> : ton mot de passe suffit pour entrer.</div>
<form method=post action=/totp/start class=actions><button class='btn primary'>Activer la 2FA (QR code)</button></form>"""
    keys = "".join(f"""<div class=field><div><b>{e(p['name'])}</b><small>ajoutée le {p['created']}</small></div>
<form method=post action=/passkey/delete><input type=hidden name=id value='{e(p['id'])}'>
<button class='btn danger'>Supprimer</button></form></div>""" for p in db["passkeys"])
    sessions = len(db["sessions"])
    body = f"""{header("/securite")}{flash_note(msg)}{error_note(err)}<div class=grid style='align-items:start'>
<section class='card s7'><h2>Double authentification (TOTP)</h2>{totp}</section>
<section class='card s5'><h2>Mot de passe</h2>
<form method=post action=/password>
<div class=field><div><b>Actuel</b></div><input type=password name=current autocomplete=current-password required></div>
<div class=field><div><b>Nouveau</b><small>{auth.MIN_PASSWORD} caractères minimum</small></div>
<input type=password name=password autocomplete=new-password required minlength={auth.MIN_PASSWORD}></div>
<div class=field><div><b>Confirmation</b></div><input type=password name=confirm autocomplete=new-password required></div>
<div class=actions><button class='btn primary'>Changer le mot de passe</button></div></form>
<p class=sub style='margin-bottom:0'>Changer le mot de passe déconnecte tous les appareils.</p></section>
<section class='card s7'><h2>Passkeys</h2><p class=sub style='margin-top:0'>Connexion sans mot de passe avec
l'empreinte, le visage ou le code de ton appareil, ou une clé de sécurité.</p>
{keys or "<p>Aucune passkey.</p>"}<div id=pk-msg class='note bad' hidden></div>
<div class=actions><input type=text id=pk-name placeholder='Nom (ex. Téléphone)' maxlength=40>
<button class='btn primary' data-passkey=register>＋ Ajouter une passkey</button></div></section>
<section class='card s5'><h2>Sessions</h2><p>{sessions} appareil(s) connecté(s).</p>
<div class=actions><form method=post action=/logout-others><button class=btn>Déconnecter les autres appareils</button></form>
<form method=post action=/logout><button class='btn danger'>Se déconnecter</button></form></div></section></div>
<script src=/static/passkey.js></script>"""
    return page("Sécurité · Actualisation", body)


HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                               "img-src 'self' data:; frame-ancestors 'none'; form-action 'self'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin", "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
PUBLIC = ("/confirm", "/login", "/login/totp", "/setup", "/static/passkey.js",
          "/passkey/login/begin", "/passkey/login/finish")
COOKIE, PRE_COOKIE = "ft_session", "ft_pre"
AUTH_PATHS = {"/login", "/login/totp", "/setup", "/securite", "/password", "/logout", "/logout-others",
              "/totp/start", "/totp/confirm", "/totp/disable", "/passkey/register/begin", "/passkey/register/finish",
              "/passkey/delete", "/passkey/login/begin", "/passkey/login/finish"}


class Handler(BaseHTTPRequestHandler):
    def send(self, body, code=200, ctype="text/html; charset=utf-8", cookies=()):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        for k, v in HEADERS.items():
            self.send_header(k, v)
        for c in cookies:
            self.send_header("Set-Cookie", c)
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, to, cookies=()):
        self.send_response(303)
        self.send_header("Location", to)
        for c in cookies:
            self.send_header("Set-Cookie", c)
        self.end_headers()

    def json(self, data, code=200, cookies=()):
        self.send(json.dumps(data).encode(), code, "application/json", cookies)

    def cookie(self, name):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return None

    def set_cookie(self, name, value, max_age):
        secure = "; Secure" if bot.BASE_URL.startswith("https") else ""
        return f"{name}={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}{secure}"

    def ip(self):
        # Behind a reverse proxy the real client is in X-Forwarded-For; auth.blocked also has a global limit.
        return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

    def login_done(self, json_reply=False):
        token = auth.new_session(self.headers.get("User-Agent"))
        cookies = [self.set_cookie(COOKIE, token, auth.SESSION_MAX), self.set_cookie(PRE_COOKIE, "", 0)]
        return self.json({"ok": True}, cookies=cookies) if json_reply else self.redirect("/", cookies)

    def pre_ok(self):
        """Password checked, TOTP still expected (short-lived marker set by /login)."""
        exp, data = auth.pending.get(self.cookie(PRE_COOKIE) or "", (0, None))
        return data == "totp" and exp > bot.time.time()

    def authed(self, path):
        if AUTH_MODE == "proxy" or path in PUBLIC:
            return True
        return auth.session_ok(self.cookie(COOKIE))

    def token_ok(self, token):
        p = state["pending"]
        return bool(p and token) and bot.secrets.compare_digest(token, p["token"])

    def do_GET(self):
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        msg = qs.get("msg", [""])[0]
        if AUTH_MODE == "builtin" and not auth.configured() and url.path not in ("/setup", "/static/passkey.js", "/confirm"):
            return self.send(auth_page("Configuration requise", "<div class='note info'>Ouvre le lien de configuration "
                                       "affiché dans les logs du container.</div>"), 403)
        if AUTH_MODE == "proxy" and url.path in AUTH_PATHS:
            return self.send(notice_page("Introuvable", "Cette page n'existe pas."), 404)
        if not self.authed(url.path):
            return self.redirect("/login")
        if url.path == "/confirm":
            token = qs.get("t", [""])[0]
            if not self.token_ok(token):
                return self.send(notice_page("Lien expiré", "Ce lien a déjà été utilisé ou n'est plus valable."), 404)
            return self.send(confirm_page(token))
        if url.path == "/static/passkey.js":
            return self.send(PASSKEY_JS, ctype="text/javascript; charset=utf-8")
        if url.path == "/setup":
            token = qs.get("token", [""])[0]
            if auth.configured() or not auth.setup_token or not bot.secrets.compare_digest(token, auth.setup_token):
                return self.send(auth_page("Lien invalide", "<div class='note bad'>Lien de configuration invalide "
                                           "ou déjà utilisé.</div>"), 403)
            return self.send(setup_page(token))
        if url.path == "/login":
            return self.send(login_page())
        if url.path == "/login/totp":
            return self.send(totp_login_page()) if self.pre_ok() else self.redirect("/login")
        if url.path.startswith("/shots/"):
            f = bot.SHOTS / Path(url.path).name
            return self.send(f.read_bytes(), ctype="image/png") if f.is_file() else self.send("", 404)
        if url.path == "/":
            return self.send(dashboard(msg))
        if url.path == "/reglages":
            return self.send(settings_page(msg))
        if url.path == "/securite":
            return self.send(security_page(msg))
        self.send(notice_page("Introuvable", "Cette page n'existe pas."), 404)

    def do_POST(self):
        origin = self.headers.get("Origin")
        if origin and origin != bot.BASE_URL:  # CSRF guard (cookies are also SameSite=Strict)
            return self.send("", 403)
        length = min(int(self.headers.get("Content-Length", 0)), 64 * 1024)
        raw = self.rfile.read(length).decode()
        if (self.headers.get("Content-Type") or "").startswith("application/json"):
            form = json.loads(raw or "{}")
        else:
            form = {k: v[0] for k, v in parse_qs(raw).items()}
        path = urlparse(self.path).path
        if AUTH_MODE == "proxy" and path in AUTH_PATHS:
            return self.send("", 404)
        if not self.authed(path):
            return self.send("", 403)
        if path in ("/login", "/login/totp", "/passkey/login/finish", "/password", "/totp/disable") \
                and auth.blocked(self.ip()):
            err = "Trop de tentatives. Réessaie dans 15 minutes."
            if path.startswith("/passkey"):
                return self.json({"error": err}, 429)
            return self.send(security_page("", err) if path in ("/password", "/totp/disable") else login_page(err), 429)
        return self.post(path, form)

    def post(self, path, form):
        ip = self.ip()
        # --- authentication
        if path == "/setup":
            if auth.configured() or not auth.setup_token or not bot.secrets.compare_digest(form.get("token", ""), auth.setup_token):
                return self.send("", 403)
            if err := auth.password_problem(form.get("password", ""), form.get("confirm", "")):
                return self.send(setup_page(form["token"], err))
            auth.set_password(form["password"])
            auth.setup_token = None
            return self.login_done()
        if path == "/login":
            db = auth.load()
            if not auth.check_password(form.get("password", ""), db["password"]):
                auth.failed(ip)
                return self.send(login_page("Mot de passe incorrect."), 401)
            if db.get("totp"):
                pre = auth.remember("totp")
                return self.redirect("/login/totp", [self.set_cookie(PRE_COOKIE, pre, 300)])
            return self.login_done()
        if path == "/login/totp":
            if not self.pre_ok():
                return self.redirect("/login")
            with auth.lock:
                db = auth.load()
                ok = auth.totp_ok(db, form.get("code", ""))
                auth.save(db)
            if not ok:
                auth.failed(ip)
                return self.send(totp_login_page("Code incorrect."), 401)
            auth.recall(self.cookie(PRE_COOKIE))
            return self.login_done()
        if path == "/passkey/login/begin":
            state_id, options = auth.passkey_login_begin()
            return self.json({"state": state_id, "options": options})
        if path == "/passkey/login/finish":
            try:
                auth.passkey_login_finish(form.get("state"), form.get("credential") or {})
            except Exception:
                auth.failed(ip)
                return self.json({"error": "Passkey refusée."}, 401)
            return self.login_done(json_reply=True)
        if path == "/logout":
            auth.end_session(self.cookie(COOKIE))
            return self.redirect("/login", [self.set_cookie(COOKIE, "", 0)])
        if path == "/logout-others":
            auth.end_session(self.cookie(COOKIE), others=True)
            return self.redirect("/securite?msg=others")
        # --- security settings (logged in)
        if path == "/password":
            db = auth.load()
            if not auth.check_password(form.get("current", ""), db["password"]):
                auth.failed(ip)
                return self.send(security_page("", "Mot de passe actuel incorrect."), 401)
            if err := auth.password_problem(form.get("password", ""), form.get("confirm", "")):
                return self.send(security_page("", err))
            auth.set_password(form["password"])
            return self.login_done()
        if path == "/totp/start":
            secret = auth.new_totp_secret()
            auth.pending["totp-setup"] = (bot.time.time() + 600, secret)
            return self.send(security_page("", "", secret))
        if path == "/totp/confirm":
            secret = auth.recall("totp-setup")
            if not secret:
                return self.redirect("/securite")
            with auth.lock:
                db = auth.load()
                if not auth.totp_ok(db, form.get("code", ""), secret):
                    auth.pending["totp-setup"] = (bot.time.time() + 600, secret)
                    return self.send(security_page("", "Code incorrect, réessaie.", secret))
                db["totp"] = secret
                auth.save(db)
            return self.redirect("/securite?msg=totp-on")
        if path == "/totp/disable":
            with auth.lock:
                db = auth.load()
                if not auth.check_password(form.get("password", ""), db["password"]):
                    auth.failed(ip)
                    return self.send(security_page("", "Mot de passe incorrect."), 401)
                db.pop("totp", None)
                auth.save(db)
            return self.redirect("/securite?msg=totp-off")
        if path == "/passkey/register/begin":
            state_id, options = auth.passkey_register_begin()
            return self.json({"state": state_id, "options": options})
        if path == "/passkey/register/finish":
            try:
                auth.passkey_register_finish(form.get("state"), form.get("credential") or {}, form.get("name"))
            except Exception as ex:
                return self.json({"error": f"Passkey refusée : {ex}"}, 400)
            return self.json({"ok": True})
        if path == "/passkey/delete":
            auth.delete_passkey(form.get("id"))
            return self.redirect("/securite?msg=pk-deleted")
        # --- app
        if path.startswith("/confirm"):
            with state_lock:
                if not self.token_ok(form.get("t")):
                    return self.send(notice_page("Lien expiré", "Ce lien a déjà été utilisé."), 404)
                deadline = state["pending"]["deadline"]
            if form.get("action") != "ok" or not bot.auto_ok():
                return self.redirect("/#mois")
            threading.Thread(target=bot.run_declare, args=(deadline,)).start()
            return self.send(notice_page("Actualisation lancée",
                                         "C'est parti. Tu reçois le résultat par e-mail dans quelques minutes.", "ok"))
        if path == "/reglages":
            try:
                cfg = parse_settings(form)
            except (KeyError, ValueError):
                return self.redirect("/reglages?msg=invalid")
            bot.save_settings(cfg)
            return self.redirect("/reglages?msg=settings")
        if path == "/test-notif":
            try:
                bot.notify("Test de notification", "Les notifications de l'actualisation France Travail fonctionnent.")
                return self.redirect("/reglages?msg=notif")
            except Exception as ex:
                bot.log("erreur", f"test de notification : {ex}")
                return self.redirect("/reglages?msg=notif-ko")
        if path == "/test-login":
            threading.Thread(target=bot.safe, args=(bot.check,)).start()
            return self.redirect("/reglages?msg=login")
        if path == "/reset-profile":
            threading.Thread(target=bot.reset_profile).start()
            return self.redirect("/reglages?msg=profile")
        if path == "/check":
            threading.Thread(target=bot.safe, args=(bot.check,)).start()
            return self.redirect("/?msg=check")
        if path == "/answers":
            with state_lock:
                if "effectuer" not in (state.get("status") or "").lower():
                    return self.redirect("/")
                a = bot.answers()
                a.update({k: form.get(k) == "oui" for k in QUESTIONS})
                state["answers"] = a
                bot.save_state()
            if not bot.auto_ok():
                return self.redirect("/?msg=manual#mois")
            if form.get("go") != "1":
                return self.redirect("/?msg=saved#mois")
            if state.get("running"):
                return self.redirect("/?msg=busy")
            threading.Thread(target=bot.run_declare, args=(state["deadline"],)).start()
            return self.redirect("/?msg=started")
        self.send("", 404)


state_lock = bot.state_lock
# builtin: password + optional TOTP/passkeys. proxy: an authenticating reverse proxy (Authelia…) is in front.
AUTH_MODE = os.environ.get("AUTH_MODE", "builtin")
PASSKEY_JS = (Path(__file__).parent / "static" / "passkey.js").read_bytes()

if __name__ == "__main__":
    bot.DATA.mkdir(parents=True, exist_ok=True)
    state["running"] = False  # a restart interrupts any run
    if AUTH_MODE == "builtin":
        auth.announce_setup()
    threading.Thread(target=bot.scheduler, daemon=True).start()
    ThreadingHTTPServer(("", 8080), Handler).serve_forever()
