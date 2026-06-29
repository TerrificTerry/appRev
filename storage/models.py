from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_product_id: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    reviews: Mapped[list["Review"]] = relationship(back_populates="product")

    __table_args__ = (
        UniqueConstraint("source", "source_product_id", "name", name="uq_product_source_key"),
    )


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_review_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    reviewer_name: Mapped[str | None] = mapped_column(String(255))
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    review_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price: Mapped[str | None] = mapped_column(String(100))
    availability: Mapped[str | None] = mapped_column(String(255))
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    product: Mapped[Product] = relationship(back_populates="reviews")

    __table_args__ = (
        UniqueConstraint("source", "source_review_id", name="uq_review_source_key"),
    )
