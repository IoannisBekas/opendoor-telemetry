# End-to-end test

Exercises the whole pipeline against a real PostgreSQL: applies both SQL
files, ingests SEC facts, footnote facilities, Redfin metro and a listings
sample, asserts known-good values, re-runs every source to prove
idempotency, and executes all 11 views.

Needs a database. A throwaway container is the easiest way:

```bash
docker run -d --name od-pg-test -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=opendoor -p 15432:5432 postgres:16
```

Then:

```bash
PG_DSN="postgresql://postgres:postgres@localhost:15432/opendoor" \
  python tests/e2e_test.py
```

Tear down with `docker rm -f od-pg-test`.

Note on ports: on Windows, Hyper-V reserves scattered ranges (55432 is
commonly inside one). `netsh interface ipv4 show excludedportrange
protocol=tcp` lists them; 15432 sits outside.

The assertions pin values from the 2026-Q2 10-Q. When Opendoor files a new
quarter the balance-sheet figures move and those assertions need updating —
that is intentional, it makes a silent upstream change loud.
