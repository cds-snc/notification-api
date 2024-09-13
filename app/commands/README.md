# Flask commands

Changes to the database outside Notify admin/api should be done via flask commands versus `psql` or a database client.

Flask commands must be run on a server that has the api repository installed and has access to the database, for example an api or celery pod in the kubernetes cluster.

Commands are run by specifying the group and command. You must also have the environment variable `FLASK_APP` set correctly. For example
```
FLASK_APP=application flask support list-routes
```

We currently have 4 groups of commands available: `support`, `bulk-db`, `test-data`, and `deprecated`. To see what commands are available for a group run a command such as
```
FLASK_APP=application flask support
```
