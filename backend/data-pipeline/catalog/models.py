import uuid
from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    Numeric,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
    Index,
    func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import relationship

from catalog.database import Base


class Category(Base):
    __tablename__ = "category"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_category_tenant_key"),
        {"schema": "catalog"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    key = Column(String(100), nullable=False)
    label = Column(String(255), nullable=False)
    parent_key = Column(String(100), nullable=True)


class Product(Base):
    __tablename__ = "product"
    __table_args__ = (
        CheckConstraint("type IN ('PRODUCT', 'SERVICE')", name="ck_product_type"),
        CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'RETIRED')", name="ck_product_status"
        ),
        Index("idx_product_tenant_status", "tenant_id", "status"),
        Index("idx_product_tenant_category", "tenant_id", "category"),
        {"schema": "catalog"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    type = Column(String(50), nullable=False, default="PRODUCT")
    name = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False)
    subcategory = Column(String(100), nullable=True)
    status = Column(String(50), nullable=False, default="DRAFT")
    description = Column(Text, nullable=True)

    # AI Findability / Sales Intelligence fields
    keywords = Column(ARRAY(String), nullable=False, default=list)
    use_cases = Column(ARRAY(String), nullable=False, default=list)
    target_industries = Column(ARRAY(String), nullable=False, default=list)
    ideal_customer_profile = Column(Text, nullable=True)
    value_proposition = Column(Text, nullable=True)
    competitors_beats = Column(ARRAY(String), nullable=False, default=list)
    sales_tags = Column(ARRAY(String), nullable=False, default=list)

    # Discount Guardrails
    min_discount_pct = Column(Numeric(5, 2), nullable=False, default=0)
    max_discount_pct = Column(Numeric(5, 2), nullable=False, default=0)

    # Multi-tenancy ACL & Housekeeping
    acl = Column(ARRAY(String), nullable=False, default=list)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    options = relationship(
        "ProductOption",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductOption.position",
    )
    variants = relationship(
        "Variant",
        back_populates="product",
        cascade="all, delete-orphan",
    )


class ProductOption(Base):
    __tablename__ = "product_option"
    __table_args__ = {"schema": "catalog"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalog.product.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    position = Column(Integer, nullable=False, default=0)

    product = relationship("Product", back_populates="options")
    values = relationship(
        "OptionValue",
        back_populates="option",
        cascade="all, delete-orphan",
        order_by="OptionValue.position",
    )


class OptionValue(Base):
    __tablename__ = "option_value"
    __table_args__ = {"schema": "catalog"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    option_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalog.product_option.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    value = Column(String(255), nullable=False)
    position = Column(Integer, nullable=False, default=0)

    option = relationship("ProductOption", back_populates="values")
    variants = relationship(
        "Variant",
        secondary="catalog.variant_option_value",
        back_populates="option_values",
    )


class VariantOptionValue(Base):
    __tablename__ = "variant_option_value"
    __table_args__ = (
        Index("idx_variant_opt_val_tenant_opt", "tenant_id", "option_value_id"),
        {"schema": "catalog"},
    )

    variant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalog.variant.id", ondelete="CASCADE"),
        primary_key=True,
    )
    option_value_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalog.option_value.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)


class Variant(Base):
    __tablename__ = "variant"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku", name="uq_variant_tenant_sku"),
        CheckConstraint("price >= 0", name="ck_variant_price_non_negative"),
        CheckConstraint(
            "status IN ('ACTIVE', 'RETIRED')", name="ck_variant_status"
        ),
        Index("idx_variant_tenant_product", "tenant_id", "product_id"),
        Index("idx_variant_tenant_price", "tenant_id", "price"),
        {"schema": "catalog"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalog.product.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    sku = Column(String(100), nullable=False)
    barcode = Column(String(100), nullable=True)
    price = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(10), nullable=False, default="USD")
    weight = Column(Numeric(10, 2), nullable=True)
    status = Column(String(50), nullable=False, default="ACTIVE")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    product = relationship("Product", back_populates="variants")
    option_values = relationship(
        "OptionValue",
        secondary="catalog.variant_option_value",
        back_populates="variants",
    )
    inventory_levels = relationship(
        "InventoryLevel",
        back_populates="variant",
        cascade="all, delete-orphan",
    )


class Location(Base):
    __tablename__ = "location"
    __table_args__ = (
        CheckConstraint(
            "type IN ('WAREHOUSE', 'STORE', 'SUPPLIER', 'IN_TRANSIT')",
            name="ck_location_type",
        ),
        {"schema": "catalog"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)
    sellable = Column(Boolean, nullable=False, default=True)
    priority = Column(Integer, nullable=False, default=100)
    address = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    inventory_levels = relationship(
        "InventoryLevel",
        back_populates="location",
        cascade="all, delete-orphan",
    )


class InventoryLevel(Base):
    __tablename__ = "inventory_level"
    __table_args__ = (
        UniqueConstraint("variant_id", "location_id", name="uq_inv_variant_location"),
        Index("idx_inv_level_tenant_variant", "tenant_id", "variant_id"),
        {"schema": "catalog"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    variant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalog.variant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    location_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalog.location.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    qty_on_hand = Column(Integer, nullable=False, default=0)
    qty_reserved = Column(Integer, nullable=False, default=0)
    reorder_at = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    variant = relationship("Variant", back_populates="inventory_levels")
    location = relationship("Location", back_populates="inventory_levels")
    movements = relationship(
        "StockMovement",
        back_populates="inventory_level",
        cascade="all, delete-orphan",
    )


class StockMovement(Base):
    __tablename__ = "stock_movement"
    __table_args__ = (
        CheckConstraint(
            "reason IN ('RESTOCK', 'SALE', 'RESERVE', 'RELEASE', 'TRANSFER_IN', 'TRANSFER_OUT', 'ADJUST', 'DAMAGE')",
            name="ck_stock_movement_reason",
        ),
        Index("idx_stock_mov_tenant_inv_at", "tenant_id", "inv_level_id", "at"),
        {"schema": "catalog"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    inv_level_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalog.inventory_level.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    delta = Column(Integer, nullable=False)
    reason = Column(String(50), nullable=False)
    ref_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    note = Column(Text, nullable=True)
    at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by = Column(String(255), nullable=True)

    inventory_level = relationship("InventoryLevel", back_populates="movements")
