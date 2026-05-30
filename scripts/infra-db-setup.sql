-- ─── Provision the VoIP database in the shared dymphna-infrastructure Cloud SQL ──
-- Gives the VoIP service its own database + user in the existing Cloud SQL instance,
-- alongside Onboarding / EHR / Financials (one instance, separate databases).
--
-- Easiest path is gcloud (consistent with how Onboarding was set up):
--   gcloud sql users    create voip          --instance=<INSTANCE> --password=<PASS> \
--                                            --project=dymphna-infrastructure
--   gcloud sql databases create dymphna_voip --instance=<INSTANCE> \
--                                            --project=dymphna-infrastructure
--
-- Then run the GRANT below once (PG15+ no longer grants CREATE on public by default),
-- connected to the new database as a Cloud SQL admin user:
--   psql "host=<proxy-or-ip> dbname=dymphna_voip user=<admin>" -f scripts/infra-db-setup.sql
--
-- Or do it all in SQL instead of gcloud:
--   CREATE USER voip WITH PASSWORD 'CHANGE_ME_STRONG';
--   CREATE DATABASE dymphna_voip OWNER voip;

\connect dymphna_voip
ALTER DATABASE dymphna_voip OWNER TO voip;
GRANT ALL ON SCHEMA public TO voip;
-- The app creates its tables on first boot (SQLAlchemy create_all) — no migrations.
