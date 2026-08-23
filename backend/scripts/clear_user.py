#!/usr/bin/env python3
"""
RoleSync User Data Cleanup Script
Clears all user data for a given email address across both microservice databases:
1. rolesync-micro-authservice
2. rolesync-micro-workspace

Usage:
    python clear_user.py <user_email>
    python clear_user.py starbalami00@gmail.com
"""

import sys
import subprocess

def run_psql(db_name: str, sql_command: str) -> str:
    """Executes a SQL command against the PostgreSQL container using docker exec."""
    cmd = [
        "docker", "exec", "postgres",
        "psql", "-U", "postgres",
        "-d", db_name,
        "-t", "-A",
        "-c", sql_command
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 and "ERROR" in result.stderr:
        print(f"  [!] SQL Warning/Error in {db_name}: {result.stderr.strip()}")
    return result.stdout.strip()

def clear_user_data(email: str):
    email = email.strip().lower()
    print("\n=======================================================")
    print(f"Starting cleanup for user email: '{email}'")
    print("=======================================================\n")

    # 1. Lookup auth_user_id in rolesync-micro-authservice
    sql_get_id = f"SELECT auth_user_id FROM auth_user_credentials WHERE LOWER(email) = '{email}';"
    auth_user_id = run_psql("rolesync-micro-authservice", sql_get_id)

    if not auth_user_id:
        print(f"[!] No user found in 'rolesync-micro-authservice' with email '{email}'.")
        print("Checking workspace service for orphaned records...")
    else:
        print(f"[+] Found auth_user_id: {auth_user_id}")

    # 2. Cleanup rolesync-micro-workspace database
    print("\n--- Cleaning up 'rolesync-micro-workspace' database ---")
    if auth_user_id:
        profile_id = run_psql("rolesync-micro-workspace", f"SELECT profile_id FROM workspace_profiles WHERE auth_user_id = '{auth_user_id}';")
    else:
        profile_id = ""

    if profile_id:
        print(f"[+] Found profile_id: {profile_id}")
        
        # Get workspaces owned by this profile
        ws_ids_raw = run_psql("rolesync-micro-workspace", f"SELECT workspace_id FROM workspaces WHERE owner_profile_id = '{profile_id}';")
        ws_ids = [w.strip() for w in ws_ids_raw.splitlines() if w.strip()]
        
        ws_condition = ""
        if ws_ids:
            ws_id_str = ", ".join([f"'{w}'" for w in ws_ids])
            ws_condition = f" OR workspace_id IN ({ws_id_str})"
            print(f"[+] Found {len(ws_ids)} owned workspace(s): {ws_ids}")

        # Delete child records linked to workspace or profile
        sql_ws_cleanup = f"""
            DELETE FROM saved_dashboard_layouts WHERE profile_id = '{profile_id}'{ws_condition};
            DELETE FROM workspace_task_views WHERE 1=1{ws_condition};
            DELETE FROM workspace_notes WHERE author_profile_id = '{profile_id}'{ws_condition};
            DELETE FROM workspace_agent_assignments WHERE profile_id = '{profile_id}'{ws_condition};
            DELETE FROM workspace_contexts WHERE created_by_profile_id = '{profile_id}'{ws_condition};
            DELETE FROM workspace_memberships WHERE profile_id = '{profile_id}'{ws_condition};
            DELETE FROM workspaces WHERE owner_profile_id = '{profile_id}';
            DELETE FROM onboarding_states WHERE profile_id = '{profile_id}';
            DELETE FROM workspace_preferences WHERE profile_id = '{profile_id}';
            DELETE FROM workspace_profiles WHERE profile_id = '{profile_id}';
        """
        run_psql("rolesync-micro-workspace", sql_ws_cleanup)
        print("  [+] Deleted workspace records, memberships, onboarding state, preferences, and profile.")

    elif auth_user_id:
        # Fallback profile cleanup by auth_user_id
        run_psql("rolesync-micro-workspace", f"DELETE FROM workspace_profiles WHERE auth_user_id = '{auth_user_id}';")
        print("  [+] Deleted profile matching auth_user_id.")

    # 3. Cleanup rolesync-micro-authservice database
    print("\n--- Cleaning up 'rolesync-micro-authservice' database ---")
    if auth_user_id:
        sql_auth_cleanup = f"""
            DELETE FROM token_store WHERE auth_user_id = '{auth_user_id}';
            DELETE FROM security_events WHERE auth_user_id = '{auth_user_id}';
            DELETE FROM password_reset_tokens WHERE auth_user_id = '{auth_user_id}';
            DELETE FROM oauth_identity WHERE auth_user_id = '{auth_user_id}';
            DELETE FROM otp_event_log WHERE auth_user_id = '{auth_user_id}';
            DELETE FROM auth_user_credentials WHERE auth_user_id = '{auth_user_id}';
        """
        run_psql("rolesync-micro-authservice", sql_auth_cleanup)
        print("  [+] Deleted tokens, security events, OAuth identities, password tokens, and user credentials.")
    else:
        run_psql("rolesync-micro-authservice", f"DELETE FROM auth_user_credentials WHERE LOWER(email) = '{email}';")
        print("  [+] Cleared credentials by email.")

    print(f"\n[SUCCESS] Cleanup completed successfully for '{email}'!\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python clear_user.py <email_address>")
        print("Example: python clear_user.py starbalami00@gmail.com")
        sys.exit(1)
    
    target_email = sys.argv[1]
    clear_user_data(target_email)
