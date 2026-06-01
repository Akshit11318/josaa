from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Institute(Base):
    __tablename__ = "institutes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    # Normalised institute type: IIT | NIT | IIIT | GFTI
    type: Mapped[str] = mapped_column(String(10), index=True)

    cutoffs: Mapped[list["Cutoff"]] = relationship(back_populates="institute")
    seats: Mapped[list["SeatMatrix"]] = relationship(back_populates="institute")


class Program(Base):
    __tablename__ = "programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Full JoSAA program string, e.g.
    # "Computer Science and Engineering (4 Years, Bachelor of Technology)"
    name: Mapped[str] = mapped_column(String(500), unique=True, index=True)


class Cutoff(Base):
    """One opening/closing-rank row from an ORCR result table."""

    __tablename__ = "cutoffs"
    __table_args__ = (
        UniqueConstraint(
            "year",
            "round",
            "institute_id",
            "program_id",
            "quota",
            "seat_type",
            "gender",
            name="uq_cutoff",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    round: Mapped[int] = mapped_column(Integer, index=True)

    institute_id: Mapped[int] = mapped_column(ForeignKey("institutes.id"), index=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"), index=True)

    quota: Mapped[str] = mapped_column(String(10))          # AI / HS / OS / GO ...
    seat_type: Mapped[str] = mapped_column(String(30), index=True)  # OPEN (filtered)
    gender: Mapped[str] = mapped_column(String(60), index=True)     # Gender-Neutral / Female-only...

    opening_rank: Mapped[int | None] = mapped_column(Integer)
    closing_rank: Mapped[int | None] = mapped_column(Integer, index=True)
    opening_rank_raw: Mapped[str | None] = mapped_column(String(20))
    closing_rank_raw: Mapped[str | None] = mapped_column(String(20))

    scraped_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    institute: Mapped[Institute] = relationship(back_populates="cutoffs")
    program: Mapped[Program] = relationship()


class SeatMatrix(Base):
    """Number of seats per institute/program/quota/seat_type/gender for a year."""

    __tablename__ = "seat_matrix"
    __table_args__ = (
        UniqueConstraint(
            "year",
            "institute_id",
            "program_id",
            "quota",
            "seat_type",
            "gender",
            name="uq_seat_matrix",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer, index=True)

    institute_id: Mapped[int] = mapped_column(ForeignKey("institutes.id"), index=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"), index=True)

    quota: Mapped[str] = mapped_column(String(10))
    seat_type: Mapped[str] = mapped_column(String(30), index=True)
    gender: Mapped[str] = mapped_column(String(60), index=True)

    seats: Mapped[int] = mapped_column(Integer, default=0)

    scraped_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    institute: Mapped[Institute] = relationship(back_populates="seats")
    program: Mapped[Program] = relationship()


class CrawlRun(Base):
    """Provenance / audit of each crawl unit (page + year + round + institute type)."""

    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    page: Mapped[str] = mapped_column(String(20))     # orcr | seatmatrix
    year: Mapped[int] = mapped_column(Integer)
    round: Mapped[int | None] = mapped_column(Integer)
    institute_type: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20))   # ok | error
    rows: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
