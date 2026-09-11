import logging
from sqlalchemy import text
from catalog.database import Base, get_engine
import catalog.models  # Ensure all models are registered with Base.metadata

logger = logging.getLogger("catalog.migrations")

VIEW_DDL = """
CREATE OR REPLACE VIEW catalog.v_variant_availability AS
SELECT il.tenant_id, il.variant_id,
       GREATEST(0, COALESCE(SUM(GREATEST(0, il.qty_on_hand - il.qty_reserved)), 0)) AS qty_available
FROM catalog.inventory_level il
JOIN catalog.location loc ON loc.id = il.location_id
WHERE loc.sellable = true
GROUP BY il.tenant_id, il.variant_id;
"""

GIN_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_product_keywords_gin ON catalog.product USING gin (keywords);",
    "CREATE INDEX IF NOT EXISTS idx_product_use_cases_gin ON catalog.product USING gin (use_cases);",
    "CREATE INDEX IF NOT EXISTS idx_product_target_industries_gin ON catalog.product USING gin (target_industries);",
    "CREATE INDEX IF NOT EXISTS idx_product_competitors_beats_gin ON catalog.product USING gin (competitors_beats);",
    "CREATE INDEX IF NOT EXISTS idx_product_sales_tags_gin ON catalog.product USING gin (sales_tags);",
]


def run_migrations(engine=None) -> None:
    if engine is None:
        engine = get_engine()

    # 1. Ensure schema exists
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS catalog;"))

    # 2. Create tables
    Base.metadata.create_all(bind=engine)
    logger.info("Catalog tables verified/created.")

    # 3. Create GIN indexes & View
    with engine.begin() as conn:
        for idx_sql in GIN_INDEXES:
            try:
                conn.execute(text(idx_sql))
            except Exception as e:
                logger.warning(f"Could not create GIN index '{idx_sql}': {e}")

        conn.execute(text(VIEW_DDL))
        logger.info("View catalog.v_variant_availability verified/created.")
