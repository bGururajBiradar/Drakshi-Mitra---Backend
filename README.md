# Drakshi Mitra Django API

## Local setup

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

python manage.py makemigrations api
python manage.py migrate
python manage.py seed_demo --demo
python manage.py runserver 0.0.0.0:8000
```

The demo account created by `seed_demo --demo` is:
- Phone: `9876543210`
- Passcode: `123456`

Change/delete this account before production.

## API

Base URL: `http://localhost:8000/api/`

Authentication:
- `POST /auth/login/`
- `POST /auth/signup/`
- `POST /auth/refresh/`
- `POST /auth/logout/`
- `GET /auth/me/`

Core:
- `/farms/`
- `/crop-cycles/`
- `/sprays/`
- `/labour/`
- `/timesheet/`
- `/timesheet/bulk/`
- `/fertilizers/`
- `/input-providers/`
- `/expenses/`
- `/expense-categories/`
- `/loans/`
- `/loan-providers/`
- `/loan-repayments/`
- `/dashboard/`
- `/reports/`
- `/weather/`
- `/backup/export/`
- `/backup/restore/`

## Security

The API uses JWT authentication, role checks, ownership-scoped querysets, server-side validation, protected admin endpoints, and password hashing through Django.

Production:
1. Set a strong `DJANGO_SECRET_KEY`.
2. Disable debug.
3. Restrict `ALLOWED_HOSTS` and CORS.
4. Serve through HTTPS.
5. Put PostgreSQL behind the application rather than relying on SQLite for production scale.
6. Store backup passwords separately from backup files.
