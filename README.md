# Channel Partner Application

This app serves a static application/payment UI from FastAPI and stores payment
sessions and submitted applications in MySQL.

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
- MySQL 8.0.17 or newer (for native JSON columns; SQLite is used by the
  isolated workflow tests)

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

- `DATABASE_URL`: MySQL URL in the form
  `mysql+asyncmy://USER:PASSWORD@HOST:3306/DATABASE?charset=utf8mb4`.
  URL-encode special characters in the password. SQLite is used by isolated
  tests; it is not the production database.
- `UPI_VPA`, `UPI_PAYEE_NAME`, `UPI_PAYMENT_NOTE`: authorized merchant payment
  details. Confirm the recipient details independently before accepting money.
- `APPLICATION_FEE_INR`: application fee (defaults to `299`).
- `ADMIN_PIN`: a unique secret of at least 16 characters used to protect
  `/admin`.
- `CORS_ORIGINS`: comma-separated trusted frontend origins when the frontend is
  hosted separately. The bundled UI is same-origin, so this can be empty.

Never commit `.env`, expose the admin PIN in frontend code, or leave the admin
review endpoints unauthenticated. Production should use HTTPS, database backups, and a payment gateway/webhook if
automatic verification is required.

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

## Deploy GitHub Pages frontend + MySQL API on your VPS

GitHub Pages continues to serve the static frontend. The VPS runs only the
FastAPI API and connects to MySQL. phpMyAdmin is used to create the database
and import its schema; it is not the API database driver.

### 1. Create the MySQL database and tables in phpMyAdmin

1. In your VPS hosting control panel, create a MySQL database and a dedicated
   database user. Grant that user `SELECT`, `INSERT`, `UPDATE`, and `DELETE`
   on this database. Do not use the MySQL root account for the running API.
2. Open phpMyAdmin, select the new database, choose **Import**, and import
   `app/backend/schema.mysql.sql`. The import file creates the application
   tables inside the database selected in phpMyAdmin; it does not create a
   database or database user.
3. Confirm that the `payments` and `applications` tables appear. The API also
   runs SQLAlchemy `create_all` at startup, but importing the schema first
   allows the restricted application user to run without table-creation
   privileges.

### 2. Upload and start the API on the VPS

1. Upload the project `app/backend` directory to a private server path such as
   `/opt/tata-partner-app/app/backend`. Do not upload `.env`, `.venv`,
   `__pycache__`, or local database files.
2. Install Python 3.11 or newer and create the virtual environment:

   ```sh
   cd /opt/tata-partner-app/app/backend
   python3 -m venv /opt/tata-partner-app/.venv
   /opt/tata-partner-app/.venv/bin/pip install -r requirements.txt
   ```

3. Create `/etc/tata-partner-api.env` with these settings. Replace the
   placeholders with your own values; percent-encode reserved characters in
   the MySQL password:

   ```env
   DATABASE_URL=mysql+asyncmy://DB_USER:URL_ENCODED_PASSWORD@127.0.0.1:3306/DB_NAME?charset=utf8mb4
   CORS_ORIGINS=https://ashrewd35-sys.github.io
   APP_URL=https://YOUR_API_DOMAIN
   UPI_VPA=information.tatasolar-1@okicici
   UPI_PAYEE_NAME=YOUR_AUTHORIZED_UPI_ACCOUNT_NAME
   UPI_PAYMENT_NOTE=TPS Partner Application Fee
   APPLICATION_FEE_INR=299
   ADMIN_PIN=CREATE_A_UNIQUE_SECRET_AT_LEAST_16_CHARACTERS
   ```

   Protect this file from public access (`chmod 600`) and assign it only to
   the API service user. Do not paste database or admin secrets into GitHub,
   HTML, JavaScript, or a public issue. Rotate any credential that was
   previously shared.
4. Configure a DNS name such as `api.example.com` to point to your VPS. Set up
   Nginx using `app/backend/deploy/vps/nginx-api.conf.example`, replace
   `YOUR_API_DOMAIN`, and enable HTTPS with your VPS provider's TLS/Let's
   Encrypt instructions. Do not expose Uvicorn port 8000 directly to the public
   internet; proxy HTTPS traffic through Nginx.
5. Copy `app/backend/deploy/vps/tata-partner-api.service.example` to
   `/etc/systemd/system/tata-partner-api.service`. Confirm the paths and
   service user match your VPS, then enable and start it:

   ```sh
   sudo systemctl daemon-reload
   sudo systemctl enable --now tata-partner-api
   sudo systemctl status tata-partner-api
   ```

6. Check `https://YOUR_API_DOMAIN/api/health`. It should respond with
   `{"status":"ok"}`. If it returns 503, review `sudo journalctl -u
   tata-partner-api` and verify the database name, user grants, password
   encoding, and MySQL host.

### 3. Point GitHub Pages at the VPS API

In `app/frontend/index.html`, replace the `API_BASE_URL` constant with your
HTTPS API URL, including `/api`, for example:

```js
const API_BASE_URL = "https://api.example.com/api";
```

Publish `app/frontend/index.html` as the repository-root `index.html` and
include `app/frontend/tata-power-logo.svg` beside it in the GitHub Pages
branch.
The backend CORS value must be exactly `https://ashrewd35-sys.github.io`—do
not add the repository path. Never use `CORS_ORIGINS=*` with credentials.
Restart the API after changing its environment, then test a draft only; do not
submit a real UTR or make a payment as a connectivity test.

The admin review is available at `https://YOUR_API_DOMAIN/admin`, or from the
GitHub Pages form via `?admin=1`. Keep the admin PIN private. The application
stores payment sessions and submissions in MySQL. An entered UTR remains
pending until an administrator verifies it against the recipient account.

## Tests

Run the isolated backend flow tests (they use a temporary SQLite database and
never contact production MySQL):

```powershell
Push-Location app\backend
python -m unittest discover -s tests -v
Pop-Location
```
