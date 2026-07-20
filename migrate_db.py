from firebase_db import initialize_database

if __name__ == "__main__":
    backend = initialize_database()
    print(f"Database initialization complete using {backend}.")
