web: gunicorn app:app --bind 0.0.0.0:$PORT
release: python migrate_db.py && python setup_db.py
