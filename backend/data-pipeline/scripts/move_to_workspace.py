"""Move data saved without a real workspace into one.

Before workspaces were wired through the app, the catalog UI saved everything under a
placeholder workspace id (``00000000-0000-0000-0000-000000000001``) and the knowledge vault
saved documents under ``tenant_default``. Both are workspace-scoped now, so that data has
to belong to a real workspace to be visible again.

Dry run by default: prints what would move. ``--apply`` changes the data. Running it again
finds nothing left to move. Run it inside the data-pipeline container, which has the
service's database settings:

  docker exec data-pipeline python scripts/move_to_workspace.py --workspace <uuid> \\
      --catalog-from 00000000-0000-0000-0000-000000000001 \\
      --vault-user <auth user id> [--vault-from tenant_default] [--apply]

The catalog moves as a whole (the placeholder was shared by everyone without a
workspace) and only into a workspace that has no catalog data yet, so SKUs and category
keys can't collide. Vault documents move per uploader. Vector chunks of connector syncs
(Gmail, Drive, ...) are personal and are not moved.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the service root, for its modules


def move_catalog(source: str, target: str, apply: bool) -> None:
    from sqlalchemy import text

    from catalog.database import get_engine

    with get_engine().begin() as conn:
        tables = conn.execute(
            text(
                "SELECT c.table_name FROM information_schema.columns c "
                "JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
                "WHERE c.table_schema = 'catalog' AND c.column_name = 'tenant_id' AND t.table_type = 'BASE TABLE' "
                "ORDER BY c.table_name"
            )
        ).scalars().all()
        counts = {
            table: conn.execute(text(f'SELECT count(*) FROM catalog."{table}" WHERE tenant_id = :t'), {"t": source}).scalar()
            for table in tables
        }
        existing = {
            table: conn.execute(text(f'SELECT count(*) FROM catalog."{table}" WHERE tenant_id = :t'), {"t": target}).scalar()
            for table in tables
        }
        print(f"catalog {source} -> {target}")
        for table in tables:
            print(f"  {table:24} {counts[table]:6} to move   ({existing[table]} already in the target)")
        if not any(counts.values()):
            print("  nothing to move")
            return
        if any(existing.values()):
            raise SystemExit("  refusing: the target workspace already has catalog data (SKUs or categories could collide)")
        if not apply:
            print("  dry run: pass --apply to move")
            return
        for table in tables:
            conn.execute(text(f'UPDATE catalog."{table}" SET tenant_id = :to WHERE tenant_id = :src'), {"to": target, "src": source})
        print("  moved")


def move_vault(user_id: str, source: str, target: str, apply: bool) -> None:
    import os

    import pymongo

    db = pymongo.MongoClient(os.environ.get("MONGODB_URI", "mongodb://mongodb:27017"), serverSelectionTimeoutMS=5000)[
        os.environ.get("MONGODB_DB_NAME", "rolesync_rag")
    ]
    doc_ids = [d["doc_id"] for d in db.knowledge_documents.find({"tenant_id": source, "user_id": user_id}, {"doc_id": 1})]
    chunk_filter = {
        "tenant_id": source,
        "$or": [{"doc_id": {"$in": doc_ids}}, {"doc_ref_id": {"$in": doc_ids}}, {"external_id": {"$in": doc_ids}}],
    }
    raw_filter = {"tenant_id": source, "doc_ref_id": {"$in": doc_ids}}
    config_filter = {"tenant_id": source, "user_id": user_id}
    target_has_config = db.knowledge_vault_configs.count_documents({"tenant_id": target, "user_id": user_id}) > 0

    print(f"knowledge vault of user {user_id}: {source} -> {target}")
    print(f"  documents       {len(doc_ids):6}")
    print(f"  raw documents   {db.raw_documents.count_documents(raw_filter):6}")
    print(f"  vector chunks   {db.vector_chunks.count_documents(chunk_filter) if doc_ids else 0:6}")
    print(f"  settings        {db.knowledge_vault_configs.count_documents(config_filter):6}" + ("   (target has its own; kept)" if target_has_config else ""))
    if not doc_ids and not db.knowledge_vault_configs.count_documents(config_filter):
        print("  nothing to move")
        return
    if not apply:
        print("  dry run: pass --apply to move")
        return
    if doc_ids:
        db.vector_chunks.update_many({**chunk_filter, "acl": f"tenant:{source}"}, {"$set": {"acl.$": f"tenant:{target}"}})
        db.vector_chunks.update_many(chunk_filter, {"$set": {"tenant_id": target}})
        db.raw_documents.update_many(raw_filter, {"$set": {"tenant_id": target}})
        db.knowledge_documents.update_many({"tenant_id": source, "doc_id": {"$in": doc_ids}}, {"$set": {"tenant_id": target}})
    if not target_has_config:
        db.knowledge_vault_configs.update_many(config_filter, {"$set": {"tenant_id": target}})
    print("  moved")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", required=True, help="target workspace UUID")
    parser.add_argument("--catalog-from", help="workspace id the catalog data sits under (e.g. the placeholder)")
    parser.add_argument("--vault-user", help="move this uploader's knowledge-vault documents")
    parser.add_argument("--vault-from", default="tenant_default", help="tenant the vault documents sit under")
    parser.add_argument("--apply", action="store_true", help="change the data (default: dry run)")
    args = parser.parse_args()

    target = str(UUID(args.workspace))
    if not args.catalog_from and not args.vault_user:
        parser.error("nothing to do: pass --catalog-from and/or --vault-user")
    if args.catalog_from:
        move_catalog(str(UUID(args.catalog_from)), target, args.apply)
    if args.vault_user:
        move_vault(args.vault_user.strip(), args.vault_from, target, args.apply)


if __name__ == "__main__":
    main()
