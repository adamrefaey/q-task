#!/bin/bash
# Helper script to create ORM test tables in PostgreSQL
# Usage: ./create-orm-tables.sh
#
# NOTE: This script is meant to be run manually when you need to recreate ORM tables.
# It will exit silently if run during Docker initialization without arguments.

set -e

# Exit silently if being run during Docker init without arguments
# This prevents auto-execution during container startup
if [ $# -eq 0 ] && [ -z "$RUN_DURING_INIT" ]; then
    exit 0
fi

DB_USER="${1:-test}"

# ANSI color codes
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}Creating ORM test tables in PostgreSQL...${NC}"
echo -e "${BLUE}  Database User: ${DB_USER}${NC}"
echo ""

# Read SQL from the migration file
SQL_FILE="$(dirname "$0")/02-create-orm-tables.sql"
if [ ! -f "$SQL_FILE" ]; then
    echo -e "${YELLOW}Warning: SQL file not found: ${SQL_FILE}${NC}"
    exit 1
fi

SQL=$(cat "$SQL_FILE")

# Check if we're running inside Docker container or from host
if [ -n "$POSTGRES_HOST" ]; then
    # Running from host - connect to Docker container
    PGPASSWORD="${POSTGRES_PASSWORD:-test}" psql \
        -h "${POSTGRES_HOST:-localhost}" \
        -p "${POSTGRES_PORT:-5432}" \
        -U "${DB_USER}" \
        -d "${POSTGRES_DB:-test_db}" \
        -c "$SQL"
else
    # Running inside container - use local connection
    psql -U "${DB_USER}" -d "${POSTGRES_DB:-test_db}" -c "$SQL"
fi

echo ""
echo -e "${GREEN}✓ ORM test tables created successfully!${NC}"
echo -e "${GREEN}  - Created SQLAlchemy tables: sqlalchemy_test_users, sqlalchemy_test_user_sessions${NC}"
echo -e "${GREEN}  - Created Django table: django_test_products${NC}"
echo -e "${GREEN}  - Created Tortoise table: tortoise_test_orders${NC}"
echo -e "${GREEN}  - Granted permissions to user: ${DB_USER}${NC}"

