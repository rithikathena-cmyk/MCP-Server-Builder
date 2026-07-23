from urllib.parse import quote_plus

import certifi
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


def build_connection_string(config: dict) -> str:
    db_type = config["db_type"]

    # URL-encode credentials — cloud DB passwords (PlanetScale, Neon, TiDB Cloud)
    # frequently contain characters that would otherwise break the URL.
    user = quote_plus(str(config["username"]))
    pwd = quote_plus(str(config["password"]))
    host = config["host"]
    port = config["port"]
    database = config["database"]
    use_ssl = bool(config.get("ssl", False))

    if db_type in ("MySQL", "TiDB"):
        url = f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{database}"
        if use_ssl:
            # PlanetScale / TiDB Cloud require TLS. certifi's CA bundle validates
            # their publicly-trusted certificates on any platform.
            url += f"?ssl_ca={quote_plus(certifi.where())}"
        return url

    elif db_type == "PostgreSQL":
        url = f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{database}"
        if use_ssl:
            url += "?sslmode=require"
        return url

    elif db_type == "SQL Server":
        return (
            f"mssql+pyodbc://{user}:{pwd}@{host}:{port}/{database}"
            "?driver=ODBC+Driver+17+for+SQL+Server"
        )

    else:
        raise ValueError("Unsupported database type.")


def test_connection(config: dict):
    try:
        connection_string = build_connection_string(config)

        engine = create_engine(connection_string)

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        return True, "Connection Successful"

    except SQLAlchemyError as e:
        return False, str(e)

    except Exception as e:
        return False, str(e)
