FROM python:3.12-slim-bookworm
# pg_dump must be at least the server's major version, so install the newest client from the PostgreSQL apt repo.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-17 \
    && apt-get purge -y curl gnupg && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "azure-identity>=1.17" "azure-storage-blob>=12.20"
COPY blufire_dbops.py /app/blufire_dbops.py
RUN printf '#!/bin/sh\nexec python /app/blufire_dbops.py "$@"\n' > /usr/local/bin/blufire-dbops \
    && chmod +x /usr/local/bin/blufire-dbops && useradd --uid 10001 --no-create-home dbops
USER 10001
WORKDIR /tmp
ENTRYPOINT ["blufire-dbops"]
