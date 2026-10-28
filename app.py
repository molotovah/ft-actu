"""France Travail monthly actualisation bot (browser + scheduling side).

Daily: log in, read the actualisation status and the calendar. Once per period,
e-mail a confirmation request. On confirmation (e-mail button or web UI), fill the
form with the month's answers and submit. Web UI: web.py. Selectors: STEPS.md.
"""
import email
import email.utils
import html
import imaplib
import json
import os
import random
import re
import secrets
import shutil
import smtplib
import threading
import time
import traceback
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from playwright.sync_api import sync_playwright

FT_ID = os.environ["FT_ID"]
FT_PASSWORD = os.environ["FT_PASSWORD"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
NOTIFY_TO = os.environ.get("NOTIFY_TO", GMAIL_USER)
BASE_URL = os.environ["BASE_URL"].rstrip("/")
DATA = Path(os.environ.get("DATA_DIR", "/data"))
SHOTS = DATA / "shots"
STATE_FILE = DATA / "state.json"
SETTINGS_FILE = DATA / "settings.json"
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "")

ESPACE = "https://candidat.francetravail.fr/espacepersonnel/"
CALENDAR = ("https://www.francetravail.fr/candidat/vos-droits-et-demarches/"
            "vos-demarches-aupres-de-pole-emp/le-calendrier-des-paiements.html")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
# Monthly questions: key -> form radios #reponse-oui-<key> / #reponse-non-<key>.
QUESTIONS = {
    "activites": "Avez-vous travaillé pour un employeur ou eu une activité d'entreprise ?",
    "formation": "Avez-vous été en formation ?",
    "arret-travail": "Avez-vous été en arrêt maladie ou en congé naissance / adoption ?",
    "pensions": "Avez-vous perçu une nouvelle pension d'invalidité ou de retraite ?",
}

# Editable in the web UI (/reglages), stored in settings.json.
DEFAULTS = {
    "paused": False,
    "check_start": 9, "check_end": 21,      # daily check window (hours)
    "request_days": 2,                      # request sent within the first N days of the period
    "remind_days": 3,                       # reminder N days before closing
    "auto": False,                          # declare without confirmation when all answers are Non
    "auto_delay_h": 24,                     # ... this many hours after the notice
    "defaults": {k: False for k in QUESTIONS},  # answers each new month starts from
    "notify_email": NOTIFY_TO,
    "ntfy": False, "ntfy_topic": "ft-actu-" + secrets.token_hex(4),
    # Self-hosted behind Cloudflare? Use the internal Docker URL (http://ntfy): Cloudflare may block Python clients.
    "ntfy_server": "https://ntfy.sh",
}


def settings():
    saved = json.loads(SETTINGS_FILE.read_text()) if SETTINGS_FILE.exists() else {}
    return {**DEFAULTS, **saved}


def save_settings(cfg):
    SETTINGS_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=1))


browser_lock = threading.Lock()
state_lock = threading.Lock()


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"status": None, "deadline": None, "checked_at": None,
            "pending": None, "handled": None, "history": []}


state = load_state()


def answers():
    """This period's answers (True = Oui). Reset to the default answers each new period."""
    a = state.get("answers") or {}
    if a.get("period") != state.get("deadline"):
        a = {"period": state.get("deadline"), **settings()["defaults"]}
    return a


def auto_ok():
    # Any "Oui" opens sub-forms (contracts, dates, amounts) the bot does not fill.
    a = answers()
    return not any(a[k] for k in QUESTIONS)


def save_state():
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1))


def log(result, detail="", shots=()):
    with state_lock:
        state["history"].insert(0, {"at": now_str(), "result": result,
                                    "detail": detail, "shots": list(shots)})
        del state["history"][100:]
        save_state()


def now_str():
    return datetime.now().strftime("%d/%m/%Y %H:%M")


def send_mail(subject, body, html_body=None):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = GMAIL_USER, settings()["notify_email"], subject
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        s.send_message(msg)


def push(title, message, click=None, actions=(), priority=3):
    """ntfy notification, if enabled. actions: (label, url) pairs."""
    cfg = settings()
    if not cfg["ntfy"]:
        return
    body = {"topic": cfg["ntfy_topic"], "title": title, "message": message, "priority": priority,
            "click": click or f"{BASE_URL}/",
            "actions": [{"action": "view", "label": l, "url": u, "clear": True} for l, u in actions]}
    headers = {"Authorization": f"Bearer {NTFY_TOKEN}"} if NTFY_TOKEN else {}
    req = urllib.request.Request(cfg["ntfy_server"].rstrip("/"), data=json.dumps(body).encode(), headers=headers)
    urllib.request.urlopen(req, timeout=15).close()


def notify(subject, text, html_body=None, actions=(), priority=3):
    """E-mail + ntfy. Both channels are tried; the first failure is raised afterwards."""
    errors = []
    for fn in (lambda: send_mail(subject, text, html_body),
               lambda: push(subject, text.split("\n\n")[0], actions=actions, priority=priority)):
        try:
            fn()
        except Exception as e:
            errors.append(e)
    if errors:
        raise errors[0]


# --- e-mail 2FA code -------------------------------------------------------

def message_text(msg):
    parts = []
    for part in msg.walk():
        if part.get_content_maintype() == "text":
            parts.append(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace"))
    return re.sub(r"<[^>]+>", " ", " ".join(parts))


def find_code(text):
    m = re.search(r"usage unique est le\s*:\s*(\d{8})", text)
    return m and m.group(1)


def wait_code(sent_after, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with imaplib.IMAP4_SSL("imap.gmail.com") as imap:
            imap.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            imap.select("INBOX")
            since = (sent_after - timedelta(days=1)).strftime("%d-%b-%Y")
            _, data = imap.search(None, "FROM", '"message.francetravail.fr"', "SINCE", since)
            for num in reversed(data[0].split()):
                _, raw = imap.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(raw[0][1])
                if email.utils.parsedate_to_datetime(msg["Date"]) < sent_after - timedelta(seconds=30):
                    break
                code = find_code(message_text(msg))
                if code:
                    return code
        time.sleep(5)
    raise RuntimeError("code e-mail France Travail non reçu en 3 min")


# --- browser ----------------------------------------------------------------

def click(page, selector):
    # The site's assistant widget overlay (#know_dark-background) intercepts clicks.
    page.wait_for_timeout(random.randint(800, 3500))  # human-ish pace
    page.evaluate("document.querySelectorAll('.know_div').forEach(e => e.remove())")
    page.click(selector)


def shot(page, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    fname = f"{datetime.now():%Y%m%d-%H%M%S}-{name}.png"
    page.screenshot(path=SHOTS / fname, full_page=True)
    return fname


def login(page):
    page.goto(ESPACE)
    code_requested_at = datetime.now(timezone.utc)
    end = time.time() + 300
    while time.time() < end:
        page.wait_for_timeout(1500)
        if page.url.startswith(ESPACE) and page.get_by_role("heading", name="Mon actualisation").count():
            return
        visible = lambda sel: page.locator(sel).first.is_visible()
        if visible("#pecookies-continue-btn"):
            click(page, "#pecookies-continue-btn")
        elif visible("#save-mc"):
            click(page, "#save-mc")  # trust this browser: no 2FA for 3 months
        elif visible("#code-1"):
            code = wait_code(code_requested_at)
            click(page, "#code-1")
            page.keyboard.type(code, delay=50)
            click(page, "#submit")
            page.wait_for_timeout(3000)
        elif visible("#canal-0"):
            code_requested_at = datetime.now(timezone.utc)
            click(page, "#canal-0")
            page.wait_for_timeout(3000)
        elif visible("#identifiant"):
            page.fill("#identifiant", FT_ID)
            page.fill("#password", FT_PASSWORD)
            click(page, "#submit")
            page.wait_for_timeout(3000)
    raise RuntimeError(f"connexion bloquée sur {page.url[:100]}")


def read_status(page):
    block = page.get_by_role("heading", name="Mon actualisation").locator("xpath=ancestor::*[3]").inner_text()
    status = re.search(r"Statut\s*:\s*(.+)", block)
    deadline = re.search(r"avant\s+le\s+(\d\d/\d\d/\d{4})", block)
    return (status.group(1).strip() if status else block[:80]), (deadline and deadline.group(1))


def read_calendar(page):
    """Rows of the public calendar: mois, ouverture, virement, cloture (dd/mm/yyyy)."""
    page.goto(CALENDAR)
    rows = []
    for tr in page.locator("table tr").all():
        cells = [c.strip() for c in tr.locator("td").all_inner_texts()]
        if len(cells) == 4 and all(re.fullmatch(r"\d\d/\d\d/\d{4}", c) for c in cells[1:]):
            rows.append(dict(zip(("mois", "ouverture", "virement", "cloture"), cells)))
    if not rows:
        raise RuntimeError("calendrier introuvable sur " + CALENDAR)
    return rows


def snapshot(page):
    return read_status(page) + (read_calendar(page),)


def declare(page):
    """Fill and submit the actualisation. Returns screenshot names."""
    click(page, "a:has-text(\"S'actualiser\")")
    # ponytail: assumes a fresh declaration; a half-saved draft may show a different
    # préambule button, add it here if a run ever fails on that page.
    page.wait_for_selector("#button_declarerMaSituation")
    click(page, "#button_declarerMaSituation")
    page.wait_for_url("**/actualisation/activites")
    if not auto_ok():
        raise RuntimeError("une réponse est Oui : actualisation à faire à la main")
    page.wait_for_selector("#reponse-non-activites")
    click(page, "#reponse-non-activites")
    click(page, "#valider-etape")
    page.wait_for_url("**/situations-particulieres")
    for key in ("formation", "arret-travail", "pensions"):
        page.wait_for_selector(f"#reponse-non-{key}")
        click(page, f"#reponse-non-{key}")
    click(page, "#valider-etape")
    page.wait_for_url("**/actualisation/validation")
    page.wait_for_selector("#reponse-oui-validation")
    click(page, "#reponse-oui-validation")
    recap = shot(page, "recapitulatif")
    click(page, "#valider-etape")  # final submit
    page.wait_for_url("**/confirmation", timeout=60000)
    page.wait_for_load_state("networkidle")
    done = shot(page, "confirmation")
    text = page.locator("main").inner_text()
    if "bien été validée" not in text:
        raise RuntimeError("page de confirmation inattendue")
    return [recap, done], re.search(r"Votre déclaration.*", text).group(0)


def with_browser(fn):
    with browser_lock, sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            DATA / "profile", headless=True, user_agent=UA, locale="fr-FR",
            timezone_id="Europe/Paris", viewport={"width": 1280, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            login(page)
            return fn(page)
        except Exception:
            try:
                log("erreur", traceback.format_exc(limit=3), [shot(page, "erreur")])
            except Exception:
                pass
            raise
        finally:
            ctx.close()


# --- jobs -------------------------------------------------------------------

def d(s):
    return datetime.strptime(s, "%d/%m/%Y")


def rand_time(day, start_h=9, end_h=21):
    """Random moment of `day` between start_h and end_h: no fixed monthly schedule."""
    midnight = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight + timedelta(seconds=random.randint(start_h * 3600, end_h * 3600))


def current_period(now):
    for p in state.get("calendar") or []:
        if d(p["ouverture"]) <= now < d(p["cloture"]) + timedelta(days=1):
            return p


def answer_lines():
    a = answers()
    return [(q, "Oui" if a[k] else "Non") for k, q in QUESTIONS.items()] + \
        [("Souhaitez-vous rester inscrit à France Travail ?", "Oui")]


def send_request(prefix=""):
    import web  # mail template lives with the other templates
    p = state["pending"]
    ok_url, edit_url = f"{BASE_URL}/confirm?t={p['token']}", f"{BASE_URL}/#mois"
    auto_at = p.get("auto_at") and datetime.fromisoformat(p["auto_at"]).strftime("%d/%m à %Hh%M")
    head = (f"Actualisation automatique prévue le {auto_at}." if auto_at
            else f"Actualisation à valider avant le {p['deadline']}.")
    text = (f"{head}\n\nRéponses prévues :\n" + "\n".join(f"- {q} {r}" for q, r in answer_lines()) +
            f"\n\nOK, actualiser : {ok_url}\nModifier : {edit_url}\n")
    actions = ([("OK, actualiser", ok_url)] if auto_ok() else []) + [("Modifier", edit_url)]
    notify(f"{prefix}Actualisation France Travail (avant le {p['deadline']})", text,
           web.request_mail(p["deadline"], answer_lines(), ok_url, edit_url, auto_ok(), auto_at),
           actions, priority=4)


def check(send=False):
    """Refresh status and calendar. With send, e-mail the confirmation request if needed."""
    status, deadline, calendar = with_browser(snapshot)
    with state_lock:
        state.update(status=status, deadline=deadline, calendar=calendar, checked_at=now_str())
        todo = "effectuer" in status.lower()
        if not todo:
            state["pending"] = None
        new_request = send and todo and not state["pending"] and state["handled"] != deadline
        if new_request:
            state["pending"] = {"token": secrets.token_urlsafe(24), "deadline": deadline}
            cfg = settings()
            if cfg["auto"] and auto_ok():
                state["pending"]["auto_at"] = (datetime.now() + timedelta(hours=cfg["auto_delay_h"])).isoformat()
        save_state()
    if new_request:
        send_request()
        log("demande envoyée", f"échéance {deadline}")


def run_declare(deadline):
    with state_lock:
        if state.get("running"):
            return
        state["running"], state["pending"] = True, None
        save_state()
    try:
        shots, detail = with_browser(declare)
        with state_lock:
            state["handled"], state["running"] = deadline, False
            save_state()
        log("actualisation validée", detail, shots)
        notify("Actualisation France Travail effectuée", f"{detail}\n\n{BASE_URL}/")
        check()
    except Exception as e:
        with state_lock:
            state["running"] = False
            save_state()
        notify("ÉCHEC actualisation France Travail",
               f"{e}\n\nÀ faire à la main avant le {deadline}.\n{BASE_URL}/", priority=5)


def safe(fn, *args):
    try:
        fn(*args)
    except Exception as e:
        try:
            notify("Erreur bot actualisation France Travail", f"{e}\n\n{BASE_URL}/", priority=4)
        except Exception:
            traceback.print_exc()


def reset_profile():
    """Forget the browser profile: next login asks for the e-mail code again."""
    with browser_lock:
        shutil.rmtree(DATA / "profile", ignore_errors=True)
    log("profil navigateur réinitialisé")


def scheduler():
    while True:
        tick()
        time.sleep(300)


def tick():
    cfg, now = settings(), datetime.now()
    if cfg["paused"]:
        return
    hours = cfg["check_start"], cfg["check_end"]
    with state_lock:
        period = current_period(now)
        if period and (state.get("plan") or {}).get("cloture") != period["cloture"]:
            # Like a human: some time in the first days of the window.
            day = d(period["ouverture"]) + timedelta(days=random.randint(0, max(cfg["request_days"], 1) - 1))
            at = max(rand_time(day, *hours), now + timedelta(minutes=random.randint(5, 90)))
            state["plan"] = {"cloture": period["cloture"], "request_at": at.isoformat()}
        plan = state.get("plan")
        due_request = bool(period and not state["pending"] and state["handled"] != period["cloture"]
                           and now >= datetime.fromisoformat(plan["request_at"]))
        due_check = now >= datetime.fromisoformat(state.get("next_check") or now.isoformat())
        if due_check or due_request:
            state["next_check"] = rand_time(now + timedelta(days=1), *hours).isoformat()
        if due_request:  # retry a few hours later if this attempt fails
            plan["request_at"] = (now + timedelta(minutes=random.randint(60, 240))).isoformat()
        p = state["pending"]
        due_auto = bool(p and p.get("auto_at") and cfg["auto"] and auto_ok()
                        and now >= datetime.fromisoformat(p["auto_at"]))
        remind = bool(p and not due_auto and not p.get("reminded")
                      and now >= d(p["deadline"]) - timedelta(days=cfg["remind_days"]))
        if remind:
            p["reminded"] = True
        save_state()
    if due_check or due_request:
        safe(check, due_request)
    if due_auto:
        safe(run_declare, p["deadline"])
    if remind:
        safe(send_request, "Rappel : ")
