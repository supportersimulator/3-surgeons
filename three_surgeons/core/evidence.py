"""Unified evidence store replacing 5 separate SQLite DBs.

FTS5-searchable learnings, claims, cross-exam logs, cost tracking,
A/B results, and observations. Portable, self-contained evidence system.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class EvidenceStore:
    """SQLite-backed evidence store with FTS5 full-text search.

    Tables:
        learnings     — title, content, learning_type, tags (JSON), created_at
        learnings_fts — FTS5 virtual table indexing title + content
        cross_exams   — topic, neurologist/cardiologist reports, consensus_score
        cost_tracking — surgeon, cost_usd, operation, created_at
        ab_results    — experiment_id, param, variant_a/b, verdict
        observations  — statement, confidence, evidence_grade
    """

    def __init__(self, db_path: str) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS learnings ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  title TEXT NOT NULL,"
                "  content TEXT NOT NULL,"
                "  learning_type TEXT NOT NULL,"
                "  tags TEXT NOT NULL DEFAULT '[]',"
                "  created_at TEXT NOT NULL"
                ")"
            )
            # FTS5 virtual table for full-text search on title + content
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts "
                "USING fts5(title, content, content=learnings, content_rowid=id)"
            )
            # Triggers to keep FTS in sync with learnings table
            conn.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS learnings_ai AFTER INSERT ON learnings BEGIN
                    INSERT INTO learnings_fts(rowid, title, content)
                    VALUES (new.id, new.title, new.content);
                END;
                CREATE TRIGGER IF NOT EXISTS learnings_ad AFTER DELETE ON learnings BEGIN
                    INSERT INTO learnings_fts(learnings_fts, rowid, title, content)
                    VALUES ('delete', old.id, old.title, old.content);
                END;
                CREATE TRIGGER IF NOT EXISTS learnings_au AFTER UPDATE ON learnings BEGIN
                    INSERT INTO learnings_fts(learnings_fts, rowid, title, content)
                    VALUES ('delete', old.id, old.title, old.content);
                    INSERT INTO learnings_fts(rowid, title, content)
                    VALUES (new.id, new.title, new.content);
                END;
                """
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS cross_exams ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  topic TEXT NOT NULL,"
                "  neurologist_report TEXT NOT NULL,"
                "  cardiologist_report TEXT NOT NULL,"
                "  neurologist_exploration TEXT,"
                "  cardiologist_exploration TEXT,"
                "  consensus_score REAL NOT NULL,"
                "  created_at TEXT NOT NULL"
                ")"
            )
            # Migration: add exploration columns to existing DBs
            for col in ("neurologist_exploration", "cardiologist_exploration"):
                try:
                    conn.execute(f"ALTER TABLE cross_exams ADD COLUMN {col} TEXT")
                except Exception:
                    pass  # Column already exists
            conn.execute(
                "CREATE TABLE IF NOT EXISTS cost_tracking ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  surgeon TEXT NOT NULL,"
                "  cost_usd REAL NOT NULL,"
                "  operation TEXT NOT NULL,"
                "  created_at TEXT NOT NULL"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS ab_results ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  experiment_id TEXT NOT NULL,"
                "  param TEXT NOT NULL,"
                "  variant_a TEXT NOT NULL,"
                "  variant_b TEXT NOT NULL,"
                "  verdict TEXT NOT NULL,"
                "  created_at TEXT NOT NULL"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS observations ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  statement TEXT NOT NULL,"
                "  confidence REAL NOT NULL,"
                "  evidence_grade TEXT NOT NULL,"
                "  created_at TEXT NOT NULL"
                ")"
            )
            conn.commit()

    # ── Learnings ──────────────────────────────────────────────────────

    def record_learning(
        self,
        title: str,
        content: str,
        learning_type: str,
        tags: List[str],
    ) -> None:
        """Insert a learning. FTS is updated automatically via trigger."""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO learnings (title, content, learning_type, tags, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (title, content, learning_type, json.dumps(tags), now),
            )
            conn.commit()

    @staticmethod
    def _prepare_fts_query(query: str) -> str:
        """Convert a natural-language query into an FTS5 OR query.

        Multi-word input like "GPU lock" becomes "GPU OR lock" so that
        any document matching at least one term is returned, ranked by
        relevance. Single words pass through unchanged.
        """
        terms = query.strip().split()
        if len(terms) <= 1:
            return query.strip()
        return " OR ".join(terms)

    def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """FTS5 search across learnings. Returns list of dicts.

        Multi-word queries use OR matching so results contain any
        of the search terms, ranked by FTS5 relevance.
        """
        fts_query = self._prepare_fts_query(query)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT l.id, l.title, l.content, l.learning_type, l.tags, l.created_at "
                "FROM learnings_fts f "
                "JOIN learnings l ON f.rowid = l.id "
                "WHERE learnings_fts MATCH ? "
                "ORDER BY rank "
                "LIMIT ?",
                (fts_query, limit),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "content": r["content"],
                "learning_type": r["learning_type"],
                "tags": json.loads(r["tags"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # ── Cross-Exams ────────────────────────────────────────────────────

    def record_cross_exam(
        self,
        topic: str,
        neurologist_report: str,
        cardiologist_report: str,
        consensus_score: float,
        neurologist_exploration: str = "",
        cardiologist_exploration: str = "",
    ) -> None:
        """Record a cross-examination between surgeons."""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO cross_exams "
                "(topic, neurologist_report, cardiologist_report, "
                "neurologist_exploration, cardiologist_exploration, "
                "consensus_score, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (topic, neurologist_report, cardiologist_report,
                 neurologist_exploration, cardiologist_exploration,
                 consensus_score, now),
            )
            conn.commit()

    def get_cross_exams(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent cross-exam logs, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, topic, neurologist_report, cardiologist_report, "
                "neurologist_exploration, cardiologist_exploration, "
                "consensus_score, created_at "
                "FROM cross_exams ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "topic": r["topic"],
                "neurologist_report": r["neurologist_report"],
                "cardiologist_report": r["cardiologist_report"],
                "neurologist_exploration": r["neurologist_exploration"] or "",
                "cardiologist_exploration": r["cardiologist_exploration"] or "",
                "consensus_score": r["consensus_score"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # ── Cost Tracking ──────────────────────────────────────────────────

    def track_cost(self, surgeon: str, cost_usd: float, operation: str) -> None:
        """Record a cost entry for a surgeon operation."""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO cost_tracking (surgeon, cost_usd, operation, created_at) "
                "VALUES (?, ?, ?, ?)",
                (surgeon, cost_usd, operation, now),
            )
            conn.commit()

    def get_daily_cost(self, surgeon: str) -> float:
        """Sum costs for a surgeon today (UTC). Returns 0.0 if none."""
        today = date.today().isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0.0) AS total "
                "FROM cost_tracking "
                "WHERE surgeon = ? AND created_at >= ?",
                (surgeon, today),
            ).fetchone()
        return float(row["total"])

    # ── A/B Results ────────────────────────────────────────────────────

    def record_ab_result(
        self,
        experiment_id: str,
        param: str,
        variant_a: str,
        variant_b: str,
        verdict: str,
    ) -> None:
        """Record an A/B experiment result."""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO ab_results "
                "(experiment_id, param, variant_a, variant_b, verdict, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (experiment_id, param, variant_a, variant_b, verdict, now),
            )
            conn.commit()

    # ── Observations ───────────────────────────────────────────────────

    def record_observation(
        self,
        statement: str,
        confidence: float,
        evidence_grade: str,
    ) -> None:
        """Record an observation with confidence and evidence grade."""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO observations "
                "(statement, confidence, evidence_grade, created_at) "
                "VALUES (?, ?, ?, ?)",
                (statement, confidence, evidence_grade, now),
            )
            conn.commit()

    # ── Stats ──────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, int]:
        """Return counts: total learnings, fixes, wins."""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM learnings").fetchone()[0]
            fixes = conn.execute(
                "SELECT COUNT(*) FROM learnings WHERE learning_type = 'fix'"
            ).fetchone()[0]
            wins = conn.execute(
                "SELECT COUNT(*) FROM learnings WHERE learning_type = 'win'"
            ).fetchone()[0]
        return {"total": total, "fixes": fixes, "wins": wins}

    # ── Evidence Snapshot ──────────────────────────────────────────────

    def get_evidence_snapshot(
        self, topic: str, limit: int = 30
    ) -> Dict[str, Any]:
        """Build a formatted evidence summary for a topic.

        Queries learnings via FTS, fetches related observations and A/B results,
        and returns a dict with learnings, stats, and a formatted evidence_text
        string (markdown).
        """
        learnings = self.search(topic, limit=limit)
        stats = self.get_stats()

        # Gather observations mentioning the topic
        with self._connect() as conn:
            obs_rows = conn.execute(
                "SELECT statement, confidence, evidence_grade, created_at "
                "FROM observations WHERE statement LIKE ? LIMIT ?",
                (f"%{topic}%", limit),
            ).fetchall()
            observations = [
                {
                    "statement": r["statement"],
                    "confidence": r["confidence"],
                    "evidence_grade": r["evidence_grade"],
                    "created_at": r["created_at"],
                }
                for r in obs_rows
            ]

            # Gather A/B results mentioning the topic
            ab_rows = conn.execute(
                "SELECT experiment_id, param, variant_a, variant_b, verdict, created_at "
                "FROM ab_results "
                "WHERE param LIKE ? OR verdict LIKE ? OR experiment_id LIKE ? "
                "LIMIT ?",
                (f"%{topic}%", f"%{topic}%", f"%{topic}%", limit),
            ).fetchall()
            ab_results = [
                {
                    "experiment_id": r["experiment_id"],
                    "param": r["param"],
                    "variant_a": r["variant_a"],
                    "variant_b": r["variant_b"],
                    "verdict": r["verdict"],
                    "created_at": r["created_at"],
                }
                for r in ab_rows
            ]

        # Build formatted markdown text
        lines: List[str] = []
        lines.append(f"## Evidence Snapshot: {topic}")
        lines.append(f"**Stats**: {stats['total']} learnings ({stats['fixes']} fixes, {stats['wins']} wins)")
        lines.append("")

        if learnings:
            lines.append("### Learnings")
            for lr in learnings:
                lines.append(f"- **{lr['title']}** [{lr['learning_type']}]: {lr['content']}")
            lines.append("")

        if observations:
            lines.append("### Observations")
            for ob in observations:
                lines.append(
                    f"- {ob['statement']} (confidence={ob['confidence']}, "
                    f"grade={ob['evidence_grade']})"
                )
            lines.append("")

        if ab_results:
            lines.append("### A/B Results")
            for ab in ab_results:
                lines.append(
                    f"- [{ab['experiment_id']}] {ab['param']}: "
                    f"A={ab['variant_a']} vs B={ab['variant_b']} -> {ab['verdict']}"
                )
            lines.append("")

        evidence_text = "\n".join(lines)

        return {
            "learnings": learnings,
            "observations": observations,
            "ab_results": ab_results,
            "stats": stats,
            "evidence_text": evidence_text,
        }
