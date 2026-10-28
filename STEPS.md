# France Travail – actualisation flow (recorded autumn 2026)

## Login
- Auth cookies (`amlbcookie`, `typeAM`, `TS01b578c9`, ...) are all session cookies: re-login every month.
- Unauthenticated hit on espacepersonnel redirects to
  https://authentification-candidat.francetravail.fr/connexion/XUI/?realm=/individu&goto=...#login/
- Cookie banner: `#pecookies-continue-btn` ("Continuer sans accepter").
- `#identifiant` (callback_0), `#password` (callback_1), `#submit` ("Se connecter").
- 2FA channel choice (same XUI URL, "Vérification d'identité"): `#canal-0` = e-mail (link, name callback_2), other = SMS.
  A help modal `#ftmodal-dismiss` is in the DOM but off-viewport: ignore it, click `#canal-0` directly.
- Code page ("Renseignez le code reçu"): 8 digits, inputs `#code-1`..`#code-8`.
  Click `#code-1` and type the 8 digits (auto-advance works). Submit `#submit` ("Poursuivre").
  `#bouton-annuler` = "Essayer une autre méthode".
- Code e-mail: from `nepasrepondre@message.francetravail.fr`, subject "Votre code temporaire France Travail",
  body "Votre code à usage unique est le : 12345678". Arrives within ~5 s.
- After the code ("Vous êtes connecté"): `#save-mc` = "Faire confiance à ce navigateur" (no 2FA for 3 months),
  `#not-save-mc` = always ask. Then redirect to espacepersonnel.
- Trust marker is NOT a visible long-lived cookie (checked: none on authentification-candidat).
  Probably server-side device profile. So keep a persistent browser profile AND keep the IMAP fallback.
- Each login sends a "Connexion à votre compte France Travail" e-mail (from `nepasrepondre@email.francetravail.fr`).
- Actualisation receipt e-mail: from `nepasrepondre@email.francetravail.fr`, subject "Accusé de réception de votre demande d'actualisation".

## 0. Espace personnel
- URL: https://candidat.francetravail.fr/espacepersonnel/
- Block "Mon actualisation": status text ("Statut : À effectuer J−12"), deadline text ("Actualisation à effectuer avant le 15/MM/YYYY").
- Link `S'actualiser` -> https://actualisationenrichie.francetravail.fr
- History: https://candidat.francetravail.fr/actualisation-declaree/

## 1. Préambule
- URL: https://actualisationenrichie.francetravail.fr/declaration-en-ligne/
- Text: "Actualiser ma situation du 28 <mois> au 15 <mois suivant>" (opening window).
- Button `#button_declarerMaSituation` ("Déclarer ma situation").

## 2. Étape 1 – Activités
- URL: .../declaration-en-ligne/actualisation/activites
- Period heading: "Pour la période du <début> au <fin du mois>".
- Question "Avez-vous réalisé une activité pour un employeur ou avez-vous une entreprise ?"
  - `#reponse-oui-activites` / `#reponse-non-activites`
- `#valider-etape` ("Valider et continuer"), "Finir plus tard" button has no id.
- Oui opens sub-forms for each contract (not explored).

## 3. Étape 2 – Situations particulières
- URL: .../declaration-en-ligne/actualisation/situations-particulieres
- Formation: `#reponse-oui-formation` / `#reponse-non-formation`
- Arrêt maladie / congé naissance-adoption: `#reponse-oui-arret-travail` / `#reponse-non-arret-travail`
- Nouvelle pension invalidité/retraite: `#reponse-oui-pensions` / `#reponse-non-pensions`
- `#valider-etape`, `#button_retour_navigation`

## 4. Étape 3 – Validation (recap)
- URL: .../declaration-en-ligne/actualisation/validation
- Recap of all answers, "Modifier" button per section.
- "Souhaitez-vous rester inscrit à France Travail ?": `#reponse-oui-validation` / `#reponse-non-validation`
- `#valider-etape` = FINAL SUBMIT (not modifiable online afterwards).

## 5. Confirmation
- URL: .../declaration-en-ligne/confirmation (title "Confirmation - Actualisation | France Travail")
- h1/h2 "Confirmation de votre actualisation"
- Text: "Votre déclaration mensuelle d'octobre a bien été validée le DD/MM/YYYY à HHhMM (heure de Paris)"
- "Statut : Inscrit", "Date prévisionnelle de paiement : Le DD/MM/YYYY"
- Confirmation e-mail sent; PDF receipt in "Mon historique d'actualisation".

## Gotchas
- Overlay `#know_dark-background` (assistant/accessibility widget "know_div") intercepts pointer events.
  Normal clicks time out; remove the overlay or use `click(force=True)`.
- Angular forms: click the inputs (do not set `.checked` via JS).
- Any "Oui" answer opens extra sub-forms: the bot must stop and alert instead of guessing.

## Calendar (public, no login)
- https://www.francetravail.fr/candidat/vos-droits-et-demarches/vos-demarches-aupres-de-pole-emp/le-calendrier-des-paiements.html
- One `table`: rows `td` x4 = "Allocation du mois de" | Ouverture | Virement à compter du | Clôture (dd/mm/yyyy).
- Closing = the 15th at midnight. Opening is usually the 28th (26th in February).
