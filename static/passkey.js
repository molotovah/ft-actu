// Passkeys (WebAuthn): converts the server's JSON options to/from ArrayBuffers.
const dec = s => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - s.length % 4) % 4)), c => c.charCodeAt(0)).buffer;
const enc = b => btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

async function post(url, body) {
  const r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body || {})});
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || "Erreur " + r.status);
  return data;
}

async function register() {
  const {state, options: o} = await post("/passkey/register/begin");
  o.challenge = dec(o.challenge);
  o.user.id = dec(o.user.id);
  (o.excludeCredentials || []).forEach(c => c.id = dec(c.id));
  const c = await navigator.credentials.create({publicKey: o});
  await post("/passkey/register/finish", {state, name: document.getElementById("pk-name").value, credential: {
    id: c.id, rawId: enc(c.rawId), type: c.type,
    response: {clientDataJSON: enc(c.response.clientDataJSON), attestationObject: enc(c.response.attestationObject),
               transports: c.response.getTransports ? c.response.getTransports() : []}}});
  location = "/securite?msg=pk-added";
}

async function login() {
  const {state, options: o} = await post("/passkey/login/begin");
  o.challenge = dec(o.challenge);
  (o.allowCredentials || []).forEach(c => c.id = dec(c.id));
  const c = await navigator.credentials.get({publicKey: o});
  await post("/passkey/login/finish", {state, credential: {
    id: c.id, rawId: enc(c.rawId), type: c.type,
    response: {clientDataJSON: enc(c.response.clientDataJSON), authenticatorData: enc(c.response.authenticatorData),
               signature: enc(c.response.signature), userHandle: c.response.userHandle ? enc(c.response.userHandle) : null}}});
  location = "/";
}

document.querySelectorAll("[data-passkey]").forEach(b => {
  if (!window.PublicKeyCredential) { b.disabled = true; b.title = "Navigateur sans support des passkeys"; return; }
  b.addEventListener("click", async e => {
    e.preventDefault();
    const msg = document.getElementById("pk-msg");
    msg.hidden = true;
    try { await (b.dataset.passkey === "login" ? login() : register()); }
    catch (err) { msg.textContent = err.name === "NotAllowedError" ? "Opération annulée." : err.message; msg.hidden = false; }
  });
});
