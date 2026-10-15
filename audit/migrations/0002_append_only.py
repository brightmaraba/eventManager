from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE FUNCTION prevent_audit_mutation() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'audit log is append-only';
            END $$ LANGUAGE plpgsql;
            DROP TRIGGER IF EXISTS audit_no_update ON audit_auditlog;
            CREATE TRIGGER audit_no_update
            BEFORE UPDATE OR DELETE ON audit_auditlog
            FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS audit_no_update ON audit_auditlog;
            DROP FUNCTION IF EXISTS prevent_audit_mutation();
            """,
        )
    ]
