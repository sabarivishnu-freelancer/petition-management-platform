# Render deployment checklist

## 1. Push the repository to GitHub
- Make sure the latest changes are committed and pushed to the GitHub repository that Render will connect to.

## 2. Import the project into Render
Option A (recommended): use the Render Blueprint file
- In Render, choose New + > Blueprint.
- Connect the GitHub repository.
- Render will read [render.yaml](render.yaml) and create:
  - a web service for the Flask app
  - a PostgreSQL database named petition-db

Option B: create the web service manually
- Choose New + > Web Service.
- Connect the GitHub repository.
- Set the runtime to Python 3.11.
- Build command:
  - `pip install -r requirements.txt`
- Start command:
  - `gunicorn app:app --bind 0.0.0.0:$PORT`

## 3. Configure environment variables
Add or confirm these variables in Render:
- `SECRET_KEY` = any long random secret
- `ADMIN_USER` = `admin`
- `ADMIN_PASS` = `adminpass`
- `ADMIN_EMAIL` = `admin@example.com`
- `DATABASE_URL` = automatically populated by Render if the database is created from the blueprint

## 4. Deploy
- Click Create or Deploy.
- Render will run the build, then the release step from [Procfile](Procfile):
  - `python migrate_db.py && python setup_db.py`
- The release step initializes the SQL tables and creates the admin account.

## 5. Verify the deployment
After the build completes:
- Open the public Render URL.
- Visit `/` and sign in with:
  - username: `admin`
  - password: `adminpass`

## 6. If the deployment fails
Check the Render logs for:
- missing Python packages
- missing `DATABASE_URL`
- database connection errors
- startup issues from Gunicorn
