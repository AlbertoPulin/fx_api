import psycopg2
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://neondb_owner:npg_t8J0dkZyOXqE@ep-quiet-grass-asvxlf3u-pooler.c-4.eu-central-1.aws.neon.tech/neondb?sslmode=require")

def get_connection():
    return psycopg2.connect(DATABASE_URL)