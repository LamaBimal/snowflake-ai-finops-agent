"""Shared Snowpark session for repo scripts (uses SNOWFLAKE_* env / session token)."""
import os
from snowflake.snowpark import Session


def get_session() -> Session:
    token_path = os.environ.get("SNOWFLAKE_TOKEN_FILE_PATH", "/snowflake/session/token")
    token = open(token_path).read().strip() if os.path.exists(token_path) else os.environ["SNOWFLAKE_TOKEN"]
    return Session.builder.configs({
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "host": os.environ.get("SNOWFLAKE_HOST"),
        "authenticator": "oauth",
        "token": token,
        "role": os.environ.get("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
        "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        "database": "AI_FINOPS",
    }).create()


def run_sql_file(session: Session, path: str) -> None:
    """Execute a .sql file; statements separated by a line containing only ';;' or by ';' at EOL.
    Procedure bodies use $$ quoting, so we split with the connector's own splitter."""
    from snowflake.connector.util_text import split_statements
    import io
    with open(path) as f:
        for stmt, _ in split_statements(io.StringIO(f.read()), remove_comments=True):
            if stmt.strip():
                session.sql(stmt).collect()
    print(f"ran {path}")


if __name__ == "__main__":
    import sys
    s = get_session()
    for p in sys.argv[1:]:
        run_sql_file(s, p)
