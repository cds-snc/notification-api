# Testing Write and Read instance

## Fake Replication Setup
NOTE: This setup is enough to test basic route functions with Read & Write instances. Scroll down if you need fully functional / real time replication between read and write instances.
#### 1. Setup Docker-Compose
Update local environment in your `.local.env`. You should have Read & Write URIs pointing to different instances.
```
SQLALCHEMY_DATABASE_URI=postgresql://postgres:LocalPassword@db:5432/notification_api
SQLALCHEMY_DATABASE_URI_READ=postgresql://postgres:LocalPassword@db-read:5432/notification_api
```
Start containers
```
docker compose -f ci/docker-compose-local-readwrite.yml up -d
```

#### 2. Create snapshot of the write database instance
```
pg_dump -U postgres -W -F t notification_api > /var/db-data/writedb.dump
```

#### 3. Copy snapshot of the write database instance into read instance's mounted volume on your system
```
cp ci/db-data/writedb.dump ci/db-data-read/writedb.dump
```

#### 4. Restore data from write instance on read instance
```
pg_restore -U postgres -W -d notification_api /var/db-data-read/writedb.dump
```

#### 5. Stop containers & remove data when done testing
```
docker compose -f ci/docker-compose-local-readwrite.yml down -v
rm -fr db-data*
```

## Real Replication Setup
Note: use if you need to test real time synchronization
1. run docker compose file listed below
2. take back up from an instance that has volume mounted
```
pg_basebackup -h write-db -D /var/lib/postgresql/data_sync -U replicator -P -R -X stream
```
1. stop only **read-db**
2. replace contents of **data-read** directory with contents of **data-sync**
3. start **read-db**
###### setup-replica.sh
```
#!/bin/bash
set -e

cat >> ${PGDATA}/postgresql.conf <<EOF
primary_conninfo = 'host=write-db port=5432 user=replicator password=replicatorpassword'
EOF

touch ${PGDATA}/standby.signal

pg_ctl reload
```
##### setup-replication.sh
```
#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "dev" --dbname "dev1035" <<-EOSQL
    CREATE USER replicator WITH REPLICATION ENCRYPTED PASSWORD 'replicatorpassword';
    GRANT ALL PRIVILEGES ON DATABASE dev1035 TO replicator;
EOSQL

cat >> ${PGDATA}/postgresql.conf <<EOF
wal_level = replica
archive_mode = on
archive_command = 'cd .'
max_wal_senders = 8
wal_keep_size = 8
hot_standby = on
EOF

echo "host    replication     replicator       0.0.0.0/0          md5" >> ${PGDATA}/pg_hba.conf

pg_ctl reload
```

##### docker-compose.yml
```
services:
  write-db:
    image: postgres:13  # adjust to the version you need
    container_name: write-db
    environment:
      POSTGRES_USER: <username>
      POSTGRES_PASSWORD: <password>
      POSTGRES_DB: notification_api
    volumes:
      - ./pgdata-write:/var/lib/postgresql/data
      - ./pgdata-sync:/var/lib/postgresql/data_sync
      - ./setup-replication.sh:/docker-entrypoint-initdb.d/setup-replication.sh
    ports:
      - "5432:5432"
    command: ["postgres", "-c", "log_statement=all"]

  read-db:
    image: postgres:13  # adjust to the version you need
    container_name: read-db
    depends_on:
      - write-db
    environment:
      POSTGRES_USER: <username>
      POSTGRES_PASSWORD: <password>
      POSTGRES_DB: notification_api
    volumes:
      - ./pgdata-read:/var/lib/postgresql/data
      - ./setup-replica.sh:/docker-entrypoint-initdb.d/setup-replica.sh
    ports:
      - "5433:5432"
    links:
      - write-db
    command: ["postgres", "-c", "log_statement=all"]
```