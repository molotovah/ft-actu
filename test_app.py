import email, os
for k in ("FT_ID", "FT_PASSWORD", "GMAIL_USER", "GMAIL_APP_PASSWORD", "BASE_URL", "UI_PASSWORD"):
    os.environ.setdefault(k, "x")
os.environ["DATA_DIR"] = "/tmp/ft-actu-test"
from app import find_code, message_text

raw = (b"Content-Type: text/html; charset=utf-8\r\nContent-Transfer-Encoding: quoted-printable\r\n\r\n"
       b"<p>Bonjour,</p><p>Votre code =C3=A0 usage unique est le : <b>12345678</b></p>")
assert find_code(message_text(email.message_from_bytes(raw))) == "12345678"
assert find_code("pas de code ici") is None
print("ok")

from datetime import datetime
import app
app.state["calendar"] = [{"mois": "Octobre 2026", "ouverture": "28/10/2026", "virement": "02/11/2026", "cloture": "15/11/2026"}]
assert app.current_period(datetime(2026, 11, 15, 23, 59))["mois"] == "Octobre 2026"
assert app.current_period(datetime(2026, 11, 16, 0, 1)) is None
assert app.current_period(datetime(2026, 10, 27, 12)) is None
t = app.rand_time(datetime(2026, 10, 28, 15), 8, 21)
assert t.date() == datetime(2026, 10, 28).date() and 8 <= t.hour <= 21
print("ok schedule")

import web
form = {"check_start": "9", "check_end": "21", "request_days": "2", "remind_days": "3", "auto_delay_h": "24",
        "notify_email": "a@b.fr", "ntfy_server": "https://ntfy.example.org", "ntfy_topic": "ft-actu", "auto": "1",
        "def-formation": "oui"}
c = web.parse_settings(form)
assert c["auto"] and not c["paused"] and c["defaults"]["formation"] and not c["defaults"]["activites"]
for bad in ({"check_start": "21", "check_end": "9"}, {"notify_email": "nope"}, {"ntfy": "1", "ntfy_topic": ""}):
    try:
        web.parse_settings({**form, **bad})
        raise AssertionError(bad)
    except ValueError:
        pass
print("ok settings")
