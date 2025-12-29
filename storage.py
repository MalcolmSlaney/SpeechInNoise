def relpath(*args):
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), *args)

# http://flask.pocoo.org/docs/0.11/patterns/sqlite3/
import sqlite3, os.path
from flask import g

class Database:
    # creates database if it doesn't exist; set up by schema
    def __init__(self, app, database, schema, init=[]):
        self.database = os.path.abspath(database)
        self.init = init
        if not os.path.exists(database):
            with app.app_context():
                db = self.get()
                with app.open_resource(schema, mode='r') as f:
                    db.cursor().executescript(f.read())
                db.commit()
                self.db_init_hook()

        self.app = app
        app.teardown_appcontext(lambda e: self.close())

    # returns a database connection
    def get(self):
        db = getattr(g, "_database", None)
        if db is None:
            # Add timeout for concurrent access (multiple users)
            db = g._database = sqlite3.connect(self.database, timeout=10.0)
            for i in self.init:
                self.execute(i)
        return db

    def queryall(self, query, args=()):
        cur = self.get().execute(query, args)
        rv = cur.fetchall()
        cur.close()
        return rv

    def queryone(self, query, args=()):
        cur = self.get().execute(query, args)
        rv = cur.fetchone()
        cur.close()
        return rv

    def execute(self, query, args=()):
        con = self.get()
        cur = con.cursor()
        cur.execute(query, args)
        con.commit()
        res = cur.lastrowid
        cur.close()
        return res or None

    def close(self):
        db = getattr(g, '_database', None)
        if db is not None:
             db.close()

    def db_init_hook(self):
        pass

from flask import Blueprint
import functools

# TODO?: redo? document?
class DatabaseBP(Blueprint):
    def __init__(self, db_path, schema_path, name, url_prefix=None):
        super().__init__(name, __name__, url_prefix=url_prefix)
        self._db_paths = (db_path, schema_path)
        self.record(lambda setup: self._bind_db(setup.app))

    def _route_db(self, *a, **kw):
        def wrapper(f):
            @functools.wraps(f)
            def wrapped(*ra, **kra):
                return f(self._blueprint_db, *ra, **kra)
            return self.route(*a, **kw)(wrapped)
        return wrapper

    def _bind_db(self, app):
        self._blueprint_db = None

