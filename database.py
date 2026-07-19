import os
from psycopg2 import pool

# Su Render questa variabile viene letta da Environment (dashboard -> Environment).
# Non c'è nessun valore hardcoded qui: se manca, l'app non parte e lo dice chiaramente.
DATABASE_URL = os.environ["DATABASE_URL"]

# Pool di connessioni: evita di aprire/chiudere una connessione TCP a Neon ad ogni richiesta.
# minconn=1, maxconn=10 -> alza maxconn se il traffico cresce, ma tieni un margine
# rispetto al limite massimo di connessioni concesso dal piano Neon.
connection_pool = pool.SimpleConnectionPool(1, 18, DATABASE_URL)


def get_connection():
    return connection_pool.getconn()


def release_connection(conn):
    connection_pool.putconn(conn)
