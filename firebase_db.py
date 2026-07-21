import os
import hashlib
import sqlite3
import logging
import sys
from datetime import datetime, timezone
from contextlib import closing
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

try:
    import psycopg2
except Exception:  # pragma: no cover
    psycopg2 = None

logger = logging.getLogger("firebase_db")
if not logger.handlers:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=False)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", os.path.join(os.path.dirname(__file__), "petition.sqlite3"))
BACKEND = "postgres" if DATABASE_URL else "sqlite"


def current_timestamp():
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()


def canonical_key(value):
    if not isinstance(value, str):
        return None
    return value.strip().lower()


def _placeholder():
    return "%s" if BACKEND == "postgres" else "?"


def _connect():
    if BACKEND == "postgres":
        if psycopg2 is None:
            logger.warning("DATABASE_URL is set but psycopg2 is not available; falling back to SQLite")
        else:
            try:
                kwargs = {}
                if "render" in DATABASE_URL.lower():
                    kwargs["sslmode"] = "require"
                conn = psycopg2.connect(DATABASE_URL, **kwargs)
                conn.autocommit = False
                return conn
            except Exception as e:  # pragma: no cover - runtime environment dependent
                logger.exception("Failed to connect to PostgreSQL (%s); falling back to SQLite: %s", DATABASE_URL, e)
        # Fallback to sqlite if psycopg2 missing or connection failed
        logger.info("Using SQLite fallback database at %s", SQLITE_DB_PATH)
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _initialize_database():
    global BACKEND
    if DATABASE_URL and psycopg2 is not None:
        BACKEND = "postgres"
    else:
        BACKEND = "sqlite"

    with closing(_connect()) as conn:
        if BACKEND == "postgres":
            with closing(conn.cursor()) as cursor:
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    email TEXT,
                    role TEXT NOT NULL CHECK (role IN ('student','admin')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS petitions (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    category TEXT,
                    priority TEXT,
                    status TEXT DEFAULT 'Pending',
                    signature_count INTEGER DEFAULT 0,
                    student_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS signatures (
                    id SERIAL PRIMARY KEY,
                    petition_id INTEGER NOT NULL REFERENCES petitions(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    signed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(petition_id, user_id)
                )
                """)
                cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_email_uidx ON users (lower(email)) WHERE email IS NOT NULL")
                cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS petitions_title_description_uidx ON petitions (lower(title), lower(description))")
        else:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                email TEXT,
                role TEXT NOT NULL CHECK (role IN ('student','admin')),
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS petitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT,
                priority TEXT,
                status TEXT DEFAULT 'Pending',
                signature_count INTEGER DEFAULT 0,
                student_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS signatures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                petition_id INTEGER NOT NULL REFERENCES petitions(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                signed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(petition_id, user_id)
            )
            """)
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_email_uidx ON users (lower(email))")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS petitions_title_description_uidx ON petitions (lower(title), lower(description))")
        if BACKEND == "postgres":
            conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            conn.execute("ALTER TABLE petitions ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        else:
            existing_users_columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
            if "created_at" not in existing_users_columns:
                conn.execute("ALTER TABLE users ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP")
            existing_petitions_columns = {row[1] for row in conn.execute("PRAGMA table_info(petitions)")}
            if "created_at" not in existing_petitions_columns:
                conn.execute("ALTER TABLE petitions ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP")
        conn.commit()


def initialize_database():
    _initialize_database()
    return BACKEND


_initialize_database()


def _row_to_dict(row, description=None):
    if row is None:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    if description:
        columns = []
        for item in description:
            if isinstance(item, (tuple, list)) and item:
                columns.append(item[0])
            elif hasattr(item, "name") and getattr(item, "name"):
                columns.append(item.name)
            elif isinstance(item, str):
                columns.append(item)
        if columns:
            return {column: value for column, value in zip(columns, row)}
    return row


def _fetch_one(query, params=(), fetch_key=None):
    with closing(_connect()) as conn:
        with closing(conn.cursor()) as cursor:
            cursor.execute(query.replace("%s", "?" if BACKEND == "sqlite" else "%s"), params)
            row = cursor.fetchone()
            if row is None:
                return None
            result = _row_to_dict(row, getattr(cursor, "description", None))
            if fetch_key is not None and isinstance(result, dict):
                return result.get(fetch_key)
            return result


def _fetch_all(query, params=()):
    with closing(_connect()) as conn:
        with closing(conn.cursor()) as cursor:
            cursor.execute(query.replace("%s", "?" if BACKEND == "sqlite" else "%s"), params)
            rows = cursor.fetchall() or []
            description = getattr(cursor, "description", None)
            return [_row_to_dict(row, description) for row in rows]


class DbRef:
    def __init__(self, path):
        self.path = path

    def get(self):
        if self.path == "signatures":
            rows = _fetch_all("SELECT petition_id, user_id, signed_at FROM signatures ORDER BY petition_id")
            grouped = {}
            for row in rows:
                grouped.setdefault(str(row["petition_id"]), {})[str(row["user_id"])] = {"signed_at": row.get("signed_at")}
            return grouped
        if self.path == "users":
            rows = _fetch_all("SELECT id, username, password, email, role, created_at FROM users ORDER BY id")
            return {str(row["id"]): {k: row.get(k) for k in ("id", "username", "password", "email", "role", "created_at")} for row in rows}
        return {}


def get_ref(path):
    return DbRef(path)


def get_user_by_id(user_id):
    if user_id is None:
        return None
    row = _fetch_one("SELECT id, username, password, email, role, created_at FROM users WHERE id = %s", (user_id,))
    if not row:
        return None
    row["id"] = str(user_id)
    return row


def get_user_by_username(username):
    if not username:
        return None
    row = _fetch_one(
        "SELECT id, username, password, email, role, created_at FROM users WHERE lower(username) = lower(%s)",
        (username,),
    )
    if not row:
        return None
    row["id"] = str(row.get("id"))
    return row


def get_user_by_email(email):
    if not email:
        return None
    row = _fetch_one(
        "SELECT id, username, password, email, role, created_at FROM users WHERE lower(email) = lower(%s)",
        (email,),
    )
    if row is None:
        return None
    row["id"] = str(row.get("id"))
    return row


def create_user(username, password_hash, email, role):
    username_key = canonical_key(username)
    if not username_key:
        raise ValueError("Username is required")
    if get_user_by_username(username):
        raise ValueError("Username or email already in use")
    if email and get_user_by_email(email):
        raise ValueError("Username or email already in use")
    with closing(_connect()) as conn:
        with closing(conn.cursor()) as cursor:
            if BACKEND == "postgres":
                cursor.execute(
                    "INSERT INTO users (username, password, email, role, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (username.strip(), password_hash, email.strip() if email else None, role, current_timestamp()),
                )
                row = cursor.fetchone()
                conn.commit()
                return row[0] if row else None
            cursor.execute(
                "INSERT INTO users (username, password, email, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (username.strip(), password_hash, email.strip() if email else None, role, current_timestamp()),
            )
            conn.commit()
            return cursor.lastrowid


def petition_hash(title, description):
    raw = f"{title.strip().lower()}||{description.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_petition_by_id(petition_id):
    if petition_id is None:
        return None
    row = _fetch_one(
        "SELECT id, title, description, category, priority, status, signature_count, student_id, created_at FROM petitions WHERE id = %s",
        (petition_id,),
    )
    if not row:
        return None
    row["id"] = str(petition_id)
    row["signature_count"] = row.get("signature_count", 0)
    return row


def get_petition_by_hash(title, description):
    row = _fetch_one(
        "SELECT id, title, description, category, priority, status, signature_count, student_id, created_at FROM petitions WHERE lower(title) = lower(%s) AND lower(description) = lower(%s) ORDER BY id DESC LIMIT 1",
        (title, description),
    )
    if not row:
        return None
    row["id"] = str(row.get("id"))
    row["signature_count"] = row.get("signature_count", 0)
    return row


def get_all_petitions():
    rows = _fetch_all(
        "SELECT id, title, description, category, priority, status, signature_count, student_id, created_at FROM petitions ORDER BY created_at DESC"
    )
    for row in rows:
        row["id"] = str(row.get("id"))
        row["signature_count"] = row.get("signature_count", 0)
    return rows


def get_petitions_by_student(student_id):
    if student_id is None:
        return []
    rows = _fetch_all(
        "SELECT id, title, description, category, priority, status, signature_count, student_id, created_at FROM petitions WHERE student_id = %s ORDER BY created_at DESC",
        (student_id,),
    )
    for row in rows:
        row["id"] = str(row.get("id"))
        row["signature_count"] = row.get("signature_count", 0)
    return rows


def create_petition(title, description, category, priority, student_id):
    with closing(_connect()) as conn:
        with closing(conn.cursor()) as cursor:
            if BACKEND == "postgres":
                cursor.execute(
                    "INSERT INTO petitions (title, description, category, priority, status, signature_count, student_id, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (title.strip(), description, category, priority, "Pending", 0, student_id, current_timestamp()),
                )
                petition_id = cursor.fetchone()[0]
            else:
                cursor.execute(
                    "INSERT INTO petitions (title, description, category, priority, status, signature_count, student_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (title.strip(), description, category, priority, "Pending", 0, student_id, current_timestamp()),
                )
                petition_id = cursor.lastrowid
            conn.commit()
    return petition_id


def get_signatures_by_petition(petition_id):
    rows = _fetch_all("SELECT petition_id, user_id, signed_at FROM signatures WHERE petition_id = %s", (petition_id,))
    return {str(row["user_id"]): {"signed_at": row.get("signed_at")} for row in rows}


def get_user_signatures(user_id):
    rows = _fetch_all("SELECT petition_id, user_id, signed_at FROM signatures WHERE user_id = %s", (user_id,))
    return {str(row["petition_id"]): {"signed_at": row.get("signed_at")} for row in rows}


def has_user_signed_petition(user_id, petition_id):
    row = _fetch_one("SELECT 1 FROM signatures WHERE user_id = %s AND petition_id = %s", (user_id, petition_id))
    return row is not None


def record_signature(user_id, petition_id):
    with closing(_connect()) as conn:
        with closing(conn.cursor()) as cursor:
            cursor.execute(
                "INSERT INTO signatures (petition_id, user_id, signed_at) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (petition_id, user_id, current_timestamp()),
            )
            conn.commit()
    return current_timestamp()


def increment_petition_signature_count(petition_id):
    with closing(_connect()) as conn:
        with closing(conn.cursor()) as cursor:
            cursor.execute("SELECT signature_count FROM petitions WHERE id = %s", (petition_id,))
            row = cursor.fetchone()
            current_count = row[0] if row else 0
            cursor.execute("UPDATE petitions SET signature_count = %s WHERE id = %s", (current_count + 1, petition_id))
            conn.commit()
    return current_count + 1


def update_petition_status(petition_id, status):
    with closing(_connect()) as conn:
        with closing(conn.cursor()) as cursor:
            cursor.execute("UPDATE petitions SET status = %s WHERE id = %s", (status, petition_id))
            conn.commit()


def delete_petition(petition_id):
    with closing(_connect()) as conn:
        with closing(conn.cursor()) as cursor:
            cursor.execute("DELETE FROM signatures WHERE petition_id = %s", (petition_id,))
            cursor.execute("DELETE FROM petitions WHERE id = %s", (petition_id,))
            conn.commit()


def get_all_users():
    rows = _fetch_all("SELECT id, username, password, email, role, created_at FROM users ORDER BY id")
    for row in rows:
        row["id"] = str(row.get("id"))
    return rows


def parse_iso_datetime(value):
    if not value:
        return None
    value = str(value).strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None
