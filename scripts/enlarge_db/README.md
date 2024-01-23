# Enlarge DB

## Purpose

The purpose of this script is add rows to the notification_history table. This is useful in estimating how long database-related infrastructure operations will take when performed on a database the same size as that in production.

## How to use

The script should be run in the same environment as api. Locally this can be in the api repo devcontainer, while in AWS the api kubernetes pod would be preferred.

To add 2000 rows to the table with a client_reference of "test2000" run

```
cd scripts/enlarge_db
python enlarge_db.py -n 2000 -r test2000
```

The new notifications are added in batches to improve performance, with a default batch size of 10000. You may use a different batch with the `-c` parameter, for example

```
python enlarge_db.py -n 2000 -c 101 -r test2000x101
```
