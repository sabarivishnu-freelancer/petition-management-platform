# Petition System Prototype

This project now uses a SQL-backed persistence layer that supports PostgreSQL for Render deployment and SQLite for local development.

## Database configuration

- Local development uses SQLite by default when no `DATABASE_URL` is set.
- Render deployments should provide `DATABASE_URL` from the managed Postgres instance.
- The application will initialize tables automatically on startup through the database adapter.

## Setup

1. Copy `.env.example` to `.env` and add your secret key and database settings.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create the default admin:

```bash
python setup_db.py
```

4. Run locally:

```bash
python app.py
```

Open `http://127.0.0.1:5000`.

## Render deployment

Render can deploy this app using the included `render.yaml` file.

```bash
render blueprint create --name petition-management-platform --repo <your-repo-url>
```

The service uses `gunicorn app:app --bind 0.0.0.0:$PORT` as its start command and runs the database initialization and admin bootstrap through `migrate_db.py` and `setup_db.py`.
