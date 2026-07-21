import os
import importlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_login_and_petition_flow(tmp_path):
    db_path = tmp_path / 'petition.sqlite3'
    os.environ['DATABASE_URL'] = ''
    os.environ['SQLITE_DB_PATH'] = str(db_path)
    import firebase_db
    import app as app_module

    app_module = importlib.reload(app_module)
    firebase_db = importlib.reload(firebase_db)
    firebase_db.initialize_database()

    client = app_module.app.test_client()
    response = client.post('/register', data={'username': 'tester', 'email': 'tester@example.com', 'password': 'secret', 'role': 'student'})
    assert response.status_code == 302

    response = client.post('/', data={'username': 'tester', 'password': 'secret'})
    assert response.status_code == 302
    assert response.headers['Location'] == '/student'

    response = client.post('/student', data={'title': 'Library Hours', 'description': 'We need longer library hours for students during exams.'})
    assert response.status_code == 200

    petitions = app_module.get_all_petitions()
    assert len(petitions) == 1
    assert petitions[0]['title'] == 'Library Hours'


def test_fetch_one_maps_tuple_rows(monkeypatch):
    import firebase_db

    class FakeCursor:
        def __init__(self):
            self.description = [('id',), ('username',), ('password',), ('email',), ('role',), ('created_at',)]
            self.query = None
            self.params = None

        def execute(self, query, params=()):
            self.query = query
            self.params = params

        def fetchone(self):
            return (1, 'tester', 'hash', 'tester@example.com', 'student', '2026-01-01T00:00:00')

        def fetchall(self):
            return []

        def close(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def __init__(self, cursor):
            self._cursor = cursor
            self.autocommit = False

        def cursor(self):
            return self._cursor

        def close(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    monkeypatch.setattr(firebase_db, '_connect', lambda: connection)

    row = firebase_db.get_user_by_username('tester')
    assert row['id'] == '1'
    assert row['username'] == 'tester'
    assert row['role'] == 'student'


def test_fetch_one_maps_name_attr_metadata(monkeypatch):
    import firebase_db

    class FakeColumn:
        def __init__(self, name):
            self.name = name

    class FakeCursor:
        def __init__(self):
            self.description = [FakeColumn('id'), FakeColumn('username'), FakeColumn('password'), FakeColumn('email'), FakeColumn('role'), FakeColumn('created_at')]
            self.query = None
            self.params = None

        def execute(self, query, params=()):
            self.query = query
            self.params = params

        def fetchone(self):
            return (2, 'alice', 'hash', 'alice@example.com', 'student', '2026-01-02T00:00:00')

        def fetchall(self):
            return []

        def close(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def __init__(self, cursor):
            self._cursor = cursor
            self.autocommit = False

        def cursor(self):
            return self._cursor

        def close(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    monkeypatch.setattr(firebase_db, '_connect', lambda: connection)

    row = firebase_db.get_user_by_username('alice')
    assert row['id'] == '2'
    assert row['username'] == 'alice'
    assert row['role'] == 'student'
