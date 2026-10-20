# Channel Partner Application

This app serves a static application/payment UI from FastAPI and stores payment
sessions and submitted applications in PostgreSQL.

## Payment and submission behavior

1. An applicant submits the application form. The server stores the draft with
   a new pending payment session and returns a UPI intent.
2. The applicant pays ₹299 using the configured UPI VPA, then submits the
   12-digit UTR shown on the receipt.
3. A UTR is **not proof of payment**. It is recorded as `pending_review`; the
   applicant sees a waiting state and cannot submit the application yet.
4. An authorized reviewer signs in at `/admin`, checks the actual recipient
   bank/UPI statement, and confirms or rejects the reference.
5. After confirmation, the applicant's still-open payment page detects the
   verified state and submits the application. The API independently enforces
   this gate and returns HTTP 402 before confirmation.

This project does not connect to a bank or payment gateway or automatically
verify UPI transfers. Do not describe an entered UTR as automatically verified.
The WhatsApp code in the application page is a browser-only demo: it opens a
prefilled message to the applicant's own number and compares the typed code
locally. It does not send an OTP automatically, prove phone ownership, or
protect the payment API from direct requests. Do not use this as production
identity verification. The success screen is shown only after a reviewer
confirms the payment and the server accepts the application. If an applicant
closes their browser while review is pending, they should retain their payment
session link and return to it after the reviewer confirms.

## Requirements

- Python 3.11 or newer
- PostgreSQL 14 or newer (Render PostgreSQL in production; SQLite is available
  for isolated local development)

## Local run (Windows PowerShell)

From the repository root:

```powershell
if (-not (Test-Path app\backend\.env)) { Copy-Item app\backend\.env.example app\backend\.env }
# Check that app\backend\.env targets a development database before running.
# Set its UPI payee details and a unique admin secret of at least 16 characters.
python -m venv app\backend\.venv
app\backend\.venv\Scripts\python -m pip install -r app\backend\requirements.txt
app\backend\.venv\Scripts\python -m uvicorn server:app --app-dir app\backend --host 127.0.0.1 --port 8000 --reload
```

Open <http://127.0.0.1:8000/>. The admin review page is at
<http://127.0.0.1:8000/admin>. Do not point development or test runs at a
production database or make a real payment during testing.

## Configuration

Copy `backend/.env.example` to `backend/.env` and set:

- `DATABASE_URL`: PostgreSQL connection URL. The example `.env` uses SQLite
  for isolated local development.
- `UPI_VPA`, `UPI_PAYEE_NAME`, `UPI_PAYMENT_NOTE`: authorized merchant payment
  details. Confirm the recipient details independently before accepting money.
- `APPLICATION_FEE_INR`: application fee (defaults to `299`).
- `ADMIN_PIN`: a unique secret of at least 16 characters used to protect
  `/admin`.
- `CORS_ORIGINS`: comma-separated trusted frontend origins when the frontend is
  hosted separately. The bundled UI is same-origin, so this can be empty.

Never commit `.env`, expose the admin PIN in frontend code, or leave the admin
review endpoints unauthenticated. Production should use HTTPS, a managed
database with backups, and a payment gateway/webhook if automatic verification
is required.

## API

- `POST /api/payments/initiate` — persist the application draft and create a
  pending UPI payment session. WhatsApp contact is optional and is not an
  identity verification step.
- `GET /api/payments/{id}` — retrieve the session status.
- `GET /api/payments/{id}/qr.svg` — render a QR code for the UPI intent.
- `POST /api/payments/{id}/verify` — submit a 12-digit UTR for manual review;
  this does not mark it paid.
- `POST /api/payments/{id}/fail` and `/retry` — record a failed attempt and
  start a new attempt from its stored draft.
- `POST /api/applications` — create an application only when the linked payment
  is `verified`.
- `POST /api/admin/login`, `GET /api/admin/payments`,
  `GET /api/admin/applications`, `POST /api/admin/payments/{id}/confirm`, and
  `/reject` — PIN-protected review operations.

## Deployment

The repository-root `render.yaml` creates a Render Python web service named
`registration-form-thqc`, runs the backend from `app/backend`, and checks
readiness at `/api/health`. It configures the GitHub Pages origin for CORS and
prompts for the PostgreSQL URL and UPI payee name; Render generates a strong
`ADMIN_PIN` on first Blueprint setup.

### Deploy the backend and connect GitHub Pages

1. Make sure the files are in the GitHub repository that publishes
   `https://ashrewd35-sys.github.io/Registration_Form/`. Keep its existing
   root `index.html` and `tata-power-logo.svg`, and add this project's
   `render.yaml` at the repository root plus both `app/frontend` and
   `app/backend`. The backend must include `server.py`, `requirements.txt`,
   `lib/`, `models/`, and `routers/`; the frontend copy is needed because the
   API service also serves its bundled UI. Keep the root GitHub Pages
   `index.html` and `app/frontend/index.html` in sync. Never upload
   `app/backend/.env` or `.venv`.
2. Use the Render PostgreSQL instance shown in your dashboard. Provide its
   internal connection URL in the Render service environment so database
   traffic stays on Render's private network. For local development, use the
   external URL and allow your development IP in the database access policy.
   Rotate the password if it has been shared and use only the new password.
   Never expose the URL in frontend code or GitHub.
3. In Render, choose **New + → Blueprint**, connect the GitHub repository and
   select its default branch. Render reads the root `render.yaml`. When
   prompted, provide `DATABASE_URL` (the Render internal PostgreSQL URL,
   updated with the rotated password) and `UPI_PAYEE_NAME` (the bank-registered
   name for the configured VPA). Save the generated `ADMIN_PIN`
   from the Render service's Environment page privately; it is required for
   admin review and must never be placed in the frontend.
4. Wait for the first deploy to finish. Open
   `https://registration-form-thqc.onrender.com/api/health`; it must
   return `{"status":"ok"}`. A database connection/index error means the
   service is not ready: check the PostgreSQL URL, rotated password, and
   Render database access. The service does not store submissions on its local
   filesystem; payment sessions and applications are stored in PostgreSQL.
5. Confirm the GitHub Pages `index.html` defines
   `const API_BASE_URL = "https://registration-form-thqc.onrender.com/api";`,
   then publish that file and the logo. The API CORS allowlist is set to the
   origin `https://ashrewd35-sys.github.io` (origins do not include the
   `/Registration_Form/` path). If Render assigns a different service URL,
   update this constant and `CORS_ORIGINS` in the Render service
   environment, then redeploy.
6. Test the deployed frontend with a non-payment test only: confirm the page
   loads, then verify the browser network requests reach
   `/api/payments/initiate`. Do not submit a real UTR or confirm a payment
   until the recipient VPA/name and production database are independently
   verified. Use the generated admin PIN at
   `https://registration-form-thqc.onrender.com/admin` or open
   `?admin=1` on GitHub Pages.

The blueprint uses Render's free web-service plan, which may spin down while
idle. That can delay the first request after inactivity; it does not erase
PostgreSQL data. Upgrade the service plan in Render if always-on availability is
required. The API and frontend may also be deployed together from FastAPI; when
doing so, set `CORS_ORIGINS` empty and use the same-origin API.

The backend creates the PostgreSQL tables and unique indexes during startup.
Existing MongoDB records are not copied automatically; export/import them
separately before switching a live system with data that must be retained.

## Tests

Run the isolated backend flow tests (they use a temporary SQLite database and
never contact production PostgreSQL):

```powershell
Push-Location app\backend
python -m unittest discover -s tests -v
Pop-Location
```
