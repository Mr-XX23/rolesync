import os
import sys
import psycopg2
from pymongo import MongoClient
import redis

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from module_1_document_processing.composio_connector.composio_client import ComposioClient

TARGET_EMAIL = "starbalami00@gmail.com"
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "root")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017/rolesync_rag")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))


def clean_auth_service(target_email: str) -> list[str]:
    """Purges all user records from rolesync-micro-authservice."""
    print(f"\n[1/4] Cleaning Auth Service (PostgreSQL) for email: {target_email}...")
    user_ids = []
    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            dbname="rolesync-micro-authservice",
        )
        conn.autocommit = False
        cur = conn.cursor()

        cur.execute("SELECT auth_user_id, username, email FROM auth_user_credentials WHERE email ILIKE %s;", (target_email,))
        rows = cur.fetchall()
        for r in rows:
            uid = str(r[0])
            user_ids.append(uid)
            print(f"  Found Auth User: ID={uid}, Username={r[1]}, Email={r[2]}")

        if not user_ids:
            print("  No Auth user credentials found.")
            cur.close()
            conn.close()
            return []

        for uid in user_ids:
            # 1. token_store
            cur.execute("DELETE FROM token_store WHERE auth_user_id = %s;", (uid,))
            print(f"  Deleted {cur.rowcount} rows from token_store for user {uid}")

            # 2. oauth_identity
            cur.execute("DELETE FROM oauth_identity WHERE auth_user_id = %s;", (uid,))
            print(f"  Deleted {cur.rowcount} rows from oauth_identity for user {uid}")

            # 3. password_reset_tokens
            cur.execute("DELETE FROM password_reset_tokens WHERE auth_user_id = %s;", (uid,))
            print(f"  Deleted {cur.rowcount} rows from password_reset_tokens for user {uid}")

            # 4. security_events
            cur.execute("DELETE FROM security_events WHERE auth_user_id = %s;", (uid,))
            print(f"  Deleted {cur.rowcount} rows from security_events for user {uid}")

            # 5. otp_event_log
            cur.execute("DELETE FROM otp_event_log WHERE auth_user_id = %s;", (uid,))
            print(f"  Deleted {cur.rowcount} rows from otp_event_log for user {uid}")

            # 6. email_event_log & sms_event_log
            try:
                cur.execute("DELETE FROM email_event_log WHERE auth_user_id = %s OR recipient ILIKE %s;", (uid, target_email))
                print(f"  Deleted {cur.rowcount} rows from email_event_log")
            except Exception as e:
                print(f"  email_event_log delete: {e}")

            try:
                cur.execute("DELETE FROM sms_event_log WHERE auth_user_id = %s;", (uid,))
                print(f"  Deleted {cur.rowcount} rows from sms_event_log")
            except Exception as e:
                print(f"  sms_event_log delete: {e}")

            # 7. auth_user_credentials
            cur.execute("DELETE FROM auth_user_credentials WHERE auth_user_id = %s;", (uid,))
            print(f"  Deleted {cur.rowcount} rows from auth_user_credentials for user {uid}")

        conn.commit()
        cur.close()
        conn.close()
        print("  [SUCCESS] Auth Service records deleted completely.")
    except Exception as err:
        print(f"  [ERROR] Cleaning Auth Service: {err}")

    return user_ids


def clean_workspace_service(user_ids: list[str]):
    """Purges all workspaces and profiles from rolesync-micro-workspace."""
    print(f"\n[2/4] Cleaning Workspace Service (PostgreSQL) for user_ids: {user_ids}...")
    if not user_ids:
        print("  No user IDs to clean in Workspace Service.")
        return

    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            dbname="rolesync-micro-workspace",
        )
        conn.autocommit = False
        cur = conn.cursor()

        profile_ids = []
        for uid in user_ids:
            cur.execute("SELECT profile_id, display_name FROM workspace_profiles WHERE auth_user_id = %s;", (uid,))
            rows = cur.fetchall()
            for r in rows:
                pid = str(r[0])
                profile_ids.append(pid)
                print(f"  Found Workspace Profile: profile_id={pid}, display_name={r[1]}")

        for pid in profile_ids:
            # Find owned workspaces
            cur.execute("SELECT workspace_id, name FROM workspaces WHERE owner_profile_id = %s;", (pid,))
            ws_rows = cur.fetchall()
            ws_ids = [str(w[0]) for w in ws_rows]
            if ws_ids:
                print(f"  Found Owned Workspaces: {ws_ids}")

            # 1. workspace_preferences
            cur.execute("DELETE FROM workspace_preferences WHERE profile_id = %s;", (pid,))
            print(f"  Deleted {cur.rowcount} rows from workspace_preferences")

            # 2. saved_dashboard_layouts
            cur.execute("DELETE FROM saved_dashboard_layouts WHERE profile_id = %s;", (pid,))
            print(f"  Deleted {cur.rowcount} rows from saved_dashboard_layouts")

            # 3. onboarding_states
            cur.execute("DELETE FROM onboarding_states WHERE profile_id = %s;", (pid,))
            print(f"  Deleted {cur.rowcount} rows from onboarding_states")

            # 4. workspace_agent_assignments
            cur.execute("DELETE FROM workspace_agent_assignments WHERE profile_id = %s;", (pid,))
            print(f"  Deleted {cur.rowcount} rows from workspace_agent_assignments")

            # 5. workspace_notes
            cur.execute("DELETE FROM workspace_notes WHERE author_profile_id = %s;", (pid,))
            print(f"  Deleted {cur.rowcount} rows from workspace_notes")

            # 6. workspace_contexts
            cur.execute("DELETE FROM workspace_contexts WHERE created_by_profile_id = %s;", (pid,))
            print(f"  Deleted {cur.rowcount} rows from workspace_contexts")

            # 7. workspace_memberships
            cur.execute("DELETE FROM workspace_memberships WHERE profile_id = %s;", (pid,))
            print(f"  Deleted {cur.rowcount} rows from workspace_memberships (profile)")
            if ws_ids:
                cur.execute("DELETE FROM workspace_memberships WHERE workspace_id = ANY(%s::uuid[]);", (ws_ids,))
                print(f"  Deleted {cur.rowcount} rows from workspace_memberships (workspaces)")

            # 8. workspaces
            if ws_ids:
                cur.execute("DELETE FROM workspaces WHERE owner_profile_id = %s;", (pid,))
                print(f"  Deleted {cur.rowcount} rows from workspaces")

            # 9. workspace_profiles
            cur.execute("DELETE FROM workspace_profiles WHERE profile_id = %s;", (pid,))
            print(f"  Deleted {cur.rowcount} rows from workspace_profiles")

        conn.commit()
        cur.close()
        conn.close()
        print("  [SUCCESS] Workspace Service records deleted completely.")
    except Exception as err:
        print(f"  [ERROR] Cleaning Workspace Service: {err}")


def clean_data_pipeline(user_ids: list[str], target_email: str):
    """Purges all MongoDB records, vectors, and staged events from rolesync_rag."""
    print(f"\n[3/4] Cleaning Data Pipeline & MongoDB (rolesync_rag)...")
    try:
        client = MongoClient(MONGO_URI)
        db = client.get_default_database()
        if db is None:
            db = client["rolesync_rag"]

        all_user_ids = list(set(user_ids + [
            "174df0c4-db9e-4c64-bebf-67f6b1169bca",
            "cd128ac9-1e49-46cb-98cb-ce2700fc7573",
            "usr_active"
        ]))

        email_regex = {"$regex": target_email, "$options": "i"}

        # 1. gmail_connections & gdrive_connections
        query_conn = {
            "$or": [
                {"user_id": {"$in": all_user_ids}},
                {"account_email": email_regex},
                {"user_email": email_regex},
            ]
        }
        res_gmail_conn = db.gmail_connections.delete_many(query_conn)
        print(f"  Deleted {res_gmail_conn.deleted_count} records from db.gmail_connections")

        res_gdrive_conn = db.gdrive_connections.delete_many(query_conn)
        print(f"  Deleted {res_gdrive_conn.deleted_count} records from db.gdrive_connections")

        # 2. gmail_synced_messages & gdrive_synced_files
        query_msg = {
            "$or": [
                {"user_id": {"$in": all_user_ids}},
                {"to": email_regex},
                {"from": email_regex},
                {"connection_id": {"$regex": "usr_active|174df0c4|cd128ac9", "$options": "i"}},
            ]
        }
        res_gmail_msg = db.gmail_synced_messages.delete_many(query_msg)
        print(f"  Deleted {res_gmail_msg.deleted_count} records from db.gmail_synced_messages")

        query_files = {
            "$or": [
                {"user_id": {"$in": all_user_ids}},
                {"connection_id": {"$regex": "usr_active|174df0c4|cd128ac9", "$options": "i"}},
            ]
        }
        res_gdrive_files = db.gdrive_synced_files.delete_many(query_files)
        print(f"  Deleted {res_gdrive_files.deleted_count} records from db.gdrive_synced_files")

        # 3. gmail_sync_activities & gdrive_sync_activities
        query_acts = {
            "$or": [
                {"user_id": {"$in": all_user_ids}},
                {"connection_id": {"$regex": "usr_active|174df0c4|cd128ac9", "$options": "i"}},
            ]
        }
        res_gmail_act = db.gmail_sync_activities.delete_many(query_acts)
        print(f"  Deleted {res_gmail_act.deleted_count} records from db.gmail_sync_activities")

        res_gdrive_act = db.gdrive_sync_activities.delete_many(query_acts)
        print(f"  Deleted {res_gdrive_act.deleted_count} records from db.gdrive_sync_activities")

        # 4. vector_chunks
        query_vec = {
            "$or": [
                {"user_id": {"$in": all_user_ids}},
                {"metadata.user_id": {"$in": all_user_ids}},
                {"metadata.acl": email_regex},
                {"acl": email_regex},
            ]
        }
        res_vec = db.vector_chunks.delete_many(query_vec)
        print(f"  Deleted {res_vec.deleted_count} records from db.vector_chunks")

        # 5. canonical_documents / checkpoint_batches / rejected_documents
        for col in ["canonical_documents", "checkpoint_batches", "rejected_documents"]:
            if col in db.list_collection_names():
                res = db[col].delete_many({
                    "$or": [
                        {"user_id": {"$in": all_user_ids}},
                        {"doc_id": email_regex},
                    ]
                })
                print(f"  Deleted {res.deleted_count} records from db.{col}")

        client.close()
        print("  [SUCCESS] Data Pipeline MongoDB records purged completely.")
    except Exception as err:
        print(f"  [ERROR] Cleaning MongoDB: {err}")


def clean_composio_and_redis(user_ids: list[str]):
    """Revokes connected accounts in Composio and flushes Redis caches."""
    print(f"\n[4/4] Cleaning Composio Connected Accounts & Redis Session Cache...")
    all_user_ids = list(set(user_ids + [
        "174df0c4-db9e-4c64-bebf-67f6b1169bca",
        "cd128ac9-1e49-46cb-98cb-ce2700fc7573",
        "usr_active"
    ]))

    # Composio
    try:
        composio = ComposioClient()
        if composio._composio:
            accounts = composio._composio.connected_accounts.list()
            items = getattr(accounts, "items", accounts)
            if not items and hasattr(accounts, "data"):
                items = accounts.data
            if items:
                for acc in items:
                    acc_uid = getattr(acc, "user_id", None) or (acc.get("user_id") if isinstance(acc, dict) else None)
                    acc_id = getattr(acc, "id", None) or (acc.get("id") if isinstance(acc, dict) else None)
                    acc_slug = composio._extract_toolkit_slug(acc)
                    if acc_uid in all_user_ids and acc_id:
                        print(f"  Deleting Composio connected account {acc_id} (toolkit: {acc_slug}, user: {acc_uid})...")
                        try:
                            composio._composio.connected_accounts.delete(acc_id)
                        except Exception as e:
                            print(f"    Failed to delete {acc_id}: {e}")
        else:
            for uid in all_user_ids:
                for source in ["gmail", "googledrive", "googlecalendar", "slack", "notion"]:
                    composio.disconnect_user_account(user_id=uid, source=source)
        print("  [SUCCESS] Composio OAuth connected accounts invalidated.")
    except Exception as err:
        print(f"  [WARN] Composio revocation: {err}")

    # Redis
    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)
        r.flushdb()
        print("  [SUCCESS] Redis cache flushed.")
    except Exception as err:
        print(f"  [WARN] Redis flush: {err}")


def main():
    target_email = sys.argv[1] if len(sys.argv) > 1 else TARGET_EMAIL

    print("=" * 60)
    print(f"ROLE-SYNC SYSTEM PURGE UTILITY")
    print(f"Target User: {target_email}")
    print("=" * 60)

    user_ids = clean_auth_service(target_email)
    clean_workspace_service(user_ids)
    clean_data_pipeline(user_ids, target_email)
    clean_composio_and_redis(user_ids)

    print("\n" + "=" * 60)
    print("SYSTEM CLEANUP COMPLETE!")
    print(f"User {target_email} is now fully cleared across Auth, Workspace, MongoDB, Vectors, and Composio.")
    print("The user can now perform a fresh Signup / Login without conflict.")
    print("=" * 60)


if __name__ == "__main__":
    main()

