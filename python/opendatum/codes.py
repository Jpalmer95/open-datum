"""Jurisdiction-Scoped Progressive-Disclosure Codes & Standards Engine.

Uses local SQLite FTS5 + BM25 + jurisdiction inheritance so AI agents never waste
tens of thousands of tokens loading irrelevant building codes:
  Stage 1: resolve_jurisdiction(jurisdiction, discipline) -> applicable code stack
  Stage 2: search(query, discipline, jurisdiction)        -> compact clause summaries (~150 tokens)
  Stage 3: get_clause(clause_id)                          -> full formula, parameters, rules

Supports `ingest_pack(path)` so firms/communities can index their own licensed local
municipal codes, project specifications, or regional standards locally.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


def _default_seed_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "codes" / "seed_codes.json"


class CodesEngine:
    def __init__(self, db_path: str = ":memory:", seed_path: Optional[Path] = None):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        path = seed_path or _default_seed_path()
        if path.exists():
            self.ingest_pack(path)

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jurisdictions (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                parent TEXT,
                adopted_standards_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS clauses (
                id TEXT PRIMARY KEY,
                jurisdiction TEXT NOT NULL,
                discipline TEXT NOT NULL,
                standard TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                details TEXT NOT NULL,
                formula TEXT,
                parameters_json TEXT,
                tags_text TEXT
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS clauses_fts USING fts5(
                id UNINDEXED,
                title,
                standard,
                summary,
                details,
                tags_text,
                discipline UNINDEXED,
                jurisdiction UNINDEXED
            );
            """
        )
        self.conn.commit()

    def ingest_pack(self, pack_path: Path) -> Dict[str, int]:
        """Ingests a JSON code pack (jurisdictions + clauses) into the local SQLite FTS5 index."""
        data = json.loads(Path(pack_path).read_text(encoding="utf-8"))
        j_count = 0
        c_count = 0

        cur = self.conn.cursor()
        for j in data.get("jurisdictions", []):
            cur.execute(
                """
                INSERT OR REPLACE INTO jurisdictions (code, name, parent, adopted_standards_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    j["code"].upper(),
                    j["name"],
                    j["parent"].upper() if j.get("parent") else None,
                    json.dumps(j.get("adopted_standards", [])),
                ),
            )
            j_count += 1

        for c in data.get("clauses", []):
            tags_text = " ".join(c.get("tags", []))
            cur.execute(
                """
                INSERT OR REPLACE INTO clauses
                (id, jurisdiction, discipline, standard, title, summary, details, formula, parameters_json, tags_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    c["id"],
                    c["jurisdiction"].upper(),
                    c["discipline"].lower(),
                    c["standard"],
                    c["title"],
                    c["summary"],
                    c["details"],
                    c.get("formula", ""),
                    json.dumps(c.get("parameters", {})),
                    tags_text,
                ),
            )
            cur.execute("DELETE FROM clauses_fts WHERE id = ?", (c["id"],))
            cur.execute(
                """
                INSERT INTO clauses_fts (id, title, standard, summary, details, tags_text, discipline, jurisdiction)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    c["id"],
                    c["title"],
                    c["standard"],
                    c["summary"],
                    c["details"],
                    tags_text,
                    c["discipline"].lower(),
                    c["jurisdiction"].upper(),
                ),
            )
            c_count += 1

        self.conn.commit()
        return {"jurisdictions_ingested": j_count, "clauses_ingested": c_count}

    def jurisdiction_chain(self, jurisdiction_code: str) -> List[str]:
        """Returns ordered inheritance chain from most specific to global (e.g., ['US-CA', 'US', 'INTL'])."""
        chain: List[str] = []
        curr: Optional[str] = jurisdiction_code.strip().upper()
        seen = set()
        while curr and curr not in seen:
            seen.add(curr)
            row = self.conn.execute(
                "SELECT code, parent FROM jurisdictions WHERE code = ?", (curr,)
            ).fetchone()
            if not row:
                # Fallback: strip suffix like US-CA-SF -> US-CA -> US -> INTL
                if "-" in curr:
                    curr = curr.rsplit("-", 1)[0]
                    continue
                if "INTL" not in seen:
                    chain.append("INTL")
                break
            chain.append(row["code"])
            curr = row["parent"]
        return chain or ["INTL"]

    def resolve_jurisdiction(
        self, jurisdiction: str, discipline: Optional[str] = None
    ) -> Dict[str, Any]:
        """Stage 1 progressive disclosure: identify applicable code editions & clause count."""
        chain = self.jurisdiction_chain(jurisdiction)
        layers = []
        for code in chain:
            row = self.conn.execute(
                "SELECT * FROM jurisdictions WHERE code = ?", (code,)
            ).fetchone()
            if row:
                layers.append(
                    {
                        "code": row["code"],
                        "name": row["name"],
                        "adopted_standards": json.loads(row["adopted_standards_json"]),
                    }
                )

        placeholders = ",".join("?" for _ in chain)
        params: List[Any] = list(chain)
        sql = f"SELECT COUNT(*) AS cnt FROM clauses WHERE jurisdiction IN ({placeholders})"
        if discipline:
            sql += " AND discipline = ?"
            params.append(discipline.lower())
        cnt = self.conn.execute(sql, params).fetchone()["cnt"]

        return {
            "requested_jurisdiction": jurisdiction.upper(),
            "inheritance_chain": chain,
            "discipline": discipline,
            "applicable_layers": layers,
            "indexed_clause_count": cnt,
        }

    def search(
        self,
        query: str,
        discipline: Optional[str] = None,
        jurisdiction: Optional[str] = None,
        limit: int = 6,
    ) -> List[Dict[str, Any]]:
        """Stage 2 progressive disclosure: compact FTS5 BM25 + jurisdiction-weighted search."""
        tokens = [
            "".join(ch for ch in tok if ch.isalnum() or ch in ("_", "."))
            for tok in query.strip().split()
        ]
        tokens = [t for t in tokens if t]

        chain = self.jurisdiction_chain(jurisdiction) if jurisdiction else None
        chain_rank = {code: idx for idx, code in enumerate(chain)} if chain else {}

        if tokens:
            fts_query = " OR ".join(f'"{t}"*' for t in tokens)
            sql = """
                SELECT c.id, c.jurisdiction, c.discipline, c.standard, c.title, c.summary, c.formula,
                       bm25(clauses_fts, 3.0, 2.0, 2.0, 1.0, 2.5) AS bm25_score
                FROM clauses_fts
                JOIN clauses c ON c.id = clauses_fts.id
                WHERE clauses_fts MATCH ?
            """
            params: List[Any] = [fts_query]
        else:
            sql = """
                SELECT id, jurisdiction, discipline, standard, title, summary, formula, 0.0 AS bm25_score
                FROM clauses
                WHERE 1=1
            """
            params = []

        if discipline:
            sql += " AND c.discipline = ?" if tokens else " AND discipline = ?"
            params.append(discipline.lower())
        if chain:
            placeholders = ",".join("?" for _ in chain)
            sql += (
                f" AND c.jurisdiction IN ({placeholders})"
                if tokens
                else f" AND jurisdiction IN ({placeholders})"
            )
            params.extend(chain)

        rows = self.conn.execute(sql, params).fetchall()
        results = []
        for r in rows:
            # Lower bm25 in SQLite FTS5 means better match; boost more specific jurisdictions.
            jur_penalty = chain_rank.get(r["jurisdiction"], 0) * 0.4
            sort_key = float(r["bm25_score"]) + jur_penalty
            results.append(
                (
                    sort_key,
                    {
                        "id": r["id"],
                        "jurisdiction": r["jurisdiction"],
                        "discipline": r["discipline"],
                        "standard": r["standard"],
                        "title": r["title"],
                        "summary": r["summary"],
                        "formula": r["formula"],
                    },
                )
            )
        results.sort(key=lambda x: x[0])
        return [item for _, item in results[:limit]]

    def get_clause(self, clause_id: str) -> Dict[str, Any]:
        """Stage 3 progressive disclosure: fetch full rule details, formula & numeric parameters."""
        row = self.conn.execute("SELECT * FROM clauses WHERE id = ?", (clause_id,)).fetchone()
        if not row:
            raise KeyError(f"Clause '{clause_id}' not found.")
        return {
            "id": row["id"],
            "jurisdiction": row["jurisdiction"],
            "discipline": row["discipline"],
            "standard": row["standard"],
            "title": row["title"],
            "summary": row["summary"],
            "details": row["details"],
            "formula": row["formula"],
            "parameters": json.loads(row["parameters_json"] or "{}"),
            "tags": (row["tags_text"] or "").split(),
        }
