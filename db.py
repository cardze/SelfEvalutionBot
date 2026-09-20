"""Database connection and initialization for feedback bot."""

import os
import logging
from contextlib import closing
import psycopg

logger = logging.getLogger(__name__)

# Global connection pool instance
_pool = None


def get_db_config():
    """Parse PostgreSQL connection config from environment variables."""
    config = {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "dbname": os.getenv("POSTGRES_DB", "feedback_bot"),
        "user": os.getenv("POSTGRES_USER", "postgres"),
        "password": os.getenv("POSTGRES_PASSWORD", ""),
    }
    return config


def init_database():
    """
    Initialize database connection pool and create schema if needed.
    
    Validates PostgreSQL connectivity at startup and creates required tables.
    Fails fast with clear error message if connection fails.
    
    Returns:
        psycopg.pool.ConnectionPool: The initialized connection pool
        
    Raises:
        Exception: If database connection fails or schema initialization fails
    """
    global _pool
    
    config = get_db_config()
    
    logger.info(f"Connecting to PostgreSQL: {config['host']}:{config['port']}/{config['dbname']}")
    
    try:
        # Test connection first
        test_conn = psycopg.connect(
            host=config["host"],
            port=config["port"],
            dbname=config["dbname"],
            user=config["user"],
            password=config["password"],
            connect_timeout=5,
        )
        test_conn.close()
        logger.info("✓ PostgreSQL connection successful")
    except psycopg.OperationalError as e:
        error_msg = str(e)
        if "Connection refused" in error_msg or "refused" in error_msg.lower():
            raise Exception(
                f"❌ PostgreSQL connection refused at {config['host']}:{config['port']}. "
                "Is Postgres running? Check POSTGRES_HOST and POSTGRES_PORT."
            ) from e
        elif "role" in error_msg.lower():
            raise Exception(
                f"❌ PostgreSQL authentication failed. Check POSTGRES_USER and POSTGRES_PASSWORD."
            ) from e
        elif "does not exist" in error_msg:
            raise Exception(
                f"❌ PostgreSQL database '{config['dbname']}' does not exist. "
                "Check POSTGRES_DB or create the database first."
            ) from e
        else:
            raise Exception(
                f"❌ PostgreSQL connection failed: {error_msg}. "
                "Check all POSTGRES_* environment variables."
            ) from e
    except Exception as e:
        raise Exception(
            f"❌ PostgreSQL connection failed: {str(e)}. "
            "Ensure all POSTGRES_* environment variables are set correctly."
        ) from e
    
    # Initialize schema
    _init_schema(config)
    
    # Create connection pool (optional, for future use)
    # For now we'll just verify single connection works
    logger.info("✓ Database initialization complete")
    
    return True


def _init_schema(config):
    """Create database schema if it doesn't exist."""
    # Read init.sql - db.py is in project root
    sql_path = os.path.join(os.path.dirname(__file__), "sql", "init.sql")
    
    if not os.path.exists(sql_path):
        raise Exception(f"Schema initialization file not found: {sql_path}")
    
    with open(sql_path, "r") as f:
        init_sql = f.read()
    
    # Execute schema initialization
    try:
        conn = psycopg.connect(
            host=config["host"],
            port=config["port"],
            dbname=config["dbname"],
            user=config["user"],
            password=config["password"],
        )
        with closing(conn):
            with conn.cursor() as cur:
                cur.execute(init_sql)
            conn.commit()
        logger.info("✓ Database schema initialized")
    except Exception as e:
        raise Exception(f"❌ Failed to initialize database schema: {str(e)}") from e


def get_connection():
    """
    Get a PostgreSQL connection from the pool.
    
    Returns:
        psycopg.connection.Connection: A database connection
    """
    config = get_db_config()
    return psycopg.connect(
        host=config["host"],
        port=config["port"],
        dbname=config["dbname"],
        user=config["user"],
        password=config["password"],
    )
