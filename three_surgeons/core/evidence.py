"""Unified evidence store replacing 5 separate SQLite DBs.

FTS5-searchable learnings, claims, cross-exam logs, cost tracking,
A/B results, and observations. Portable, self-contained evidence system.

Includes EBM-inspired evidence grading ladder with UP-ONLY promotion.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Evidence Grade Enum ──────────────────────────────────────────────


class EvidenceGrade(Enum):
    """EBM-inspired evidence grading. Higher weight = stronger evidence.

    Grades form an UP-ONLY ladder: once promoted, never demoted.
    Thresholds: anecdotal(1) → correlation/case_series(5@60%) →
    cohort(10@70%) → validated(20@80%).
    """

    ANECDOTAL = 0.3
    EXPERT_OPINION = 0.4
    CASE_SERIES = 0.5
    COHORT = 0.7
    VALIDATED = 0.9

    @property
    def weight(self) -> float:
        return self.value

    @property
    def rank(self) -> int:
        return _GRADE_RANK[self.name.lower()]

    def apply_to_confidence(self, base_confidence: float) -> float:
        """Discount confidence by evidence strength."""
        return base_confidence * self.weight

    @classmethod
    def from_string(cls, grade_str: str) -> EvidenceGrade:
        """Parse grade string with backward-compat aliases."""
        mapping = {
            "anecdotal": cls.ANECDOTAL,
            "anecdote": cls.ANECDOTAL,
            "expert_opinion": cls.EXPERT_OPINION,
            "opinion": cls.EXPERT_OPINION,
            "case_series": cls.CASE_SERIES,
            "correlation": cls.CASE_SERIES,
            "cohort": cls.COHORT,
            "validated": cls.VALIDATED,
            "meta_analysis": cls.VALIDATED,
        }
        return mapping.get(grade_str.lower().strip(), cls.ANECDOTAL)


_GRADE_RANK: Dict[str, int] = {
    "anecdotal": 0,
    "expert_opinion": 1,
    "case_series": 2,
    "cohort": 3,
    "validated": 4,
}

_GRADE_THRESHOLDS = [
    (20, 0.8, "validated"),
    (10, 0.7, "cohort"),
    (5, 0.6, "case_series"),
    (3, 0.5, "case_series"),
    (1, 0.0, "anecdotal"),
]


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
            # Migration: add mode_used and iteration_count columns
            for col, col_type in [("mode_used", "TEXT"), ("iteration_count", "INTEGER")]:
                try:
                    conn.execute(f"ALTER TABLE cross_exams ADD COLUMN {col} {col_type}")
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
                "  weighted_confidence REAL NOT NULL DEFAULT 0.0,"
                "  evidence_grade TEXT NOT NULL,"
                "  created_at TEXT NOT NULL"
                ")"
            )
            # Migration: add weighted_confidence to existing DBs
            try:
                conn.execute(
                    "ALTER TABLE observations ADD COLUMN "
                    "weighted_confidence REAL NOT NULL DEFAULT 0.0"
                )
            except Exception:
                pass
            conn.execute(
                "CREATE TABLE IF NOT EXISTS observation_outcomes ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  observation_id INTEGER NOT NULL,"
                "  success INTEGER NOT NULL,"
                "  created_at TEXT NOT NULL,"
                "  FOREIGN KEY (observation_id) REFERENCES observations(id)"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS evidence_grade_history ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  observation_id INTEGER NOT NULL,"
                "  old_grade TEXT NOT NULL,"
                "  new_grade TEXT NOT NULL,"
                "  reason TEXT,"
                "  outcome_count INTEGER,"
                "  success_rate REAL,"
                "  created_at TEXT NOT NULL,"
                "  FOREIGN KEY (observation_id) REFERENCES observations(id)"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS review_outcomes ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  topic TEXT NOT NULL,"
                "  mode_used TEXT NOT NULL,"
                "  iteration_count INTEGER NOT NULL,"
                "  consensus_reached INTEGER NOT NULL,"
                "  consensus_score REAL NOT NULL,"
                "  files_changed INTEGER NOT NULL DEFAULT 0,"
                "  escalation_needed INTEGER NOT NULL DEFAULT 0,"
                "  user_override TEXT,"
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
        mode_used: str = "single",
        iteration_count: int = 1,
    ) -> None:
        """Record a cross-examination between surgeons."""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO cross_exams "
                "(topic, neurologist_report, cardiologist_report, "
                "neurologist_exploration, cardiologist_exploration, "
                "consensus_score, mode_used, iteration_count, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (topic, neurologist_report, cardiologist_report,
                 neurologist_exploration, cardiologist_exploration,
                 consensus_score, mode_used, iteration_count, now),
            )
            conn.commit()

    def get_cross_exams(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent cross-exam logs, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, topic, neurologist_report, cardiologist_report, "
                "neurologist_exploration, cardiologist_exploration, "
                "consensus_score, mode_used, iteration_count, created_at "
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
                "mode_used": r["mode_used"] or "single",
                "iteration_count": r["iteration_count"] or 1,
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
    ) -> int:
        """Record an observation with EBM-weighted confidence. Returns row id."""
        grade = EvidenceGrade.from_string(evidence_grade)
        weighted = grade.apply_to_confidence(confidence)
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO observations "
                "(statement, confidence, weighted_confidence, evidence_grade, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (statement, confidence, weighted, evidence_grade, now),
            )
            conn.commit()
            return cursor.lastrowid  # type: ignore[return-value]

    def record_outcome(self, observation_id: int, success: bool) -> None:
        """Record an outcome for an observation (for grade ladder)."""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO observation_outcomes "
                "(observation_id, success, created_at) VALUES (?, ?, ?)",
                (observation_id, 1 if success else 0, now),
            )
            conn.commit()

    def get_observation_outcome_stats(
        self, observation_id: int
    ) -> Dict[str, Any]:
        """Get outcome count and success rate for an observation."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n, "
                "COALESCE(AVG(success), 0.0) AS success_rate "
                "FROM observation_outcomes WHERE observation_id = ?",
                (observation_id,),
            ).fetchone()
        return {"n": row["n"], "success_rate": row["success_rate"]}

    def auto_upgrade_grade(
        self, observation_id: int
    ) -> Optional[Dict[str, Any]]:
        """Auto-UPGRADE evidence grade based on outcomes. Never downgrades.

        Returns grade transition dict if upgraded, None otherwise.
        """
        with self._connect() as conn:
            obs = conn.execute(
                "SELECT evidence_grade FROM observations WHERE id = ?",
                (observation_id,),
            ).fetchone()
            if not obs:
                return None
            old_grade = obs["evidence_grade"]

            stats = self.get_observation_outcome_stats(observation_id)
            n, sr = stats["n"], stats["success_rate"]

            earned_grade = "anecdotal"
            for threshold_n, threshold_sr, grade in _GRADE_THRESHOLDS:
                if n >= threshold_n and sr >= threshold_sr:
                    earned_grade = grade
                    break

            old_rank = _GRADE_RANK.get(
                EvidenceGrade.from_string(old_grade).name.lower(), 0
            )
            new_rank = _GRADE_RANK.get(
                EvidenceGrade.from_string(earned_grade).name.lower(), 0
            )
            if new_rank <= old_rank:
                return None

            now = datetime.utcnow().isoformat()
            conn.execute(
                "UPDATE observations SET evidence_grade = ? WHERE id = ?",
                (earned_grade, observation_id),
            )
            conn.execute(
                "INSERT INTO evidence_grade_history "
                "(observation_id, old_grade, new_grade, reason, "
                "outcome_count, success_rate, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    observation_id,
                    old_grade,
                    earned_grade,
                    f"Auto-upgrade: n={n}, sr={sr:.2f}",
                    n,
                    sr,
                    now,
                ),
            )
            conn.commit()
        return {
            "observation_id": observation_id,
            "old_grade": old_grade,
            "new_grade": earned_grade,
            "n": n,
            "success_rate": sr,
        }

    def get_grade_history(
        self, observation_id: int
    ) -> List[Dict[str, Any]]:
        """Get grade transition history for an observation."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT old_grade, new_grade, reason, "
                "outcome_count, success_rate, created_at "
                "FROM evidence_grade_history "
                "WHERE observation_id = ? ORDER BY id",
                (observation_id,),
            ).fetchall()
        return [
            {
                "old_grade": r["old_grade"],
                "new_grade": r["new_grade"],
                "reason": r["reason"],
                "outcome_count": r["outcome_count"],
                "success_rate": r["success_rate"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # ── Review Outcomes (Adaptive Learning) ──────────────────────────

    def record_review_outcome(
        self,
        topic: str,
        mode_used: str,
        iteration_count: int,
        consensus_reached: bool,
        consensus_score: float,
        files_changed: int = 0,
        escalation_needed: bool = False,
        user_override: Optional[str] = None,
    ) -> None:
        """Record the outcome of a review loop for adaptive weight learning."""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO review_outcomes "
                "(topic, mode_used, iteration_count, consensus_reached, "
                "consensus_score, files_changed, escalation_needed, "
                "user_override, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (topic, mode_used, iteration_count, int(consensus_reached),
                 consensus_score, files_changed, int(escalation_needed),
                 user_override, now),
            )
            conn.commit()

    def get_review_outcomes(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent review outcomes, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM review_outcomes ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "topic": r["topic"],
                "mode_used": r["mode_used"],
                "iteration_count": r["iteration_count"],
                "consensus_reached": bool(r["consensus_reached"]),
                "consensus_score": r["consensus_score"],
                "files_changed": r["files_changed"],
                "escalation_needed": bool(r["escalation_needed"]),
                "user_override": r["user_override"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def get_mode_weights(self) -> Dict[str, float]:
        """Compute adaptive mode weights from outcome history.

        Weight = success_rate * avg_consensus for each mode.
        Higher weight = mode tends to produce good outcomes.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT mode_used, "
                "COUNT(*) as n, "
                "AVG(consensus_reached) as success_rate, "
                "AVG(consensus_score) as avg_consensus "
                "FROM review_outcomes GROUP BY mode_used"
            ).fetchall()
        weights = {}
        for r in rows:
            weights[r["mode_used"]] = round(
                float(r["success_rate"]) * float(r["avg_consensus"]), 3
            )
        return weights

    def export_review_outcomes(self) -> List[Dict[str, Any]]:
        """Export sanitized review outcomes for cross-machine sharing.

        Strips project-specific fields (topic, id) to prevent data leakage.
        Only statistical fields needed for weight computation are exported.
        """
        raw = self.get_review_outcomes(limit=10000)
        return [
            {
                "mode_used": r["mode_used"],
                "iteration_count": r["iteration_count"],
                "consensus_reached": r["consensus_reached"],
                "consensus_score": r["consensus_score"],
                "files_changed": r["files_changed"],
                "escalation_needed": r["escalation_needed"],
                "user_override": r["user_override"],
                "created_at": r["created_at"],
            }
            for r in raw
        ]

    def import_review_outcomes(self, data: List[Dict[str, Any]]) -> int:
        """Import review outcomes from another machine. Returns count imported.

        Accepts both sanitized exports (no topic) and legacy exports (with topic).
        Sanitized imports use '(imported)' as the topic placeholder.
        """
        count = 0
        with self._connect() as conn:
            for item in data:
                conn.execute(
                    "INSERT INTO review_outcomes "
                    "(topic, mode_used, iteration_count, consensus_reached, "
                    "consensus_score, files_changed, escalation_needed, "
                    "user_override, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (item.get("topic", "(imported)"),
                     item["mode_used"], item["iteration_count"],
                     int(item["consensus_reached"]), item["consensus_score"],
                     item.get("files_changed", 0), int(item.get("escalation_needed", False)),
                     item.get("user_override"), item["created_at"]),
                )
                count += 1
            conn.commit()
        return count

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
