"""Storage service for feedback submissions and events."""

import logging
from contextlib import closing
from uuid import UUID
from typing import Optional
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from db import get_connection

logger = logging.getLogger(__name__)

# Allowed feedback_events.event_type values.
# Must match feedback_events_event_type_check in sql/init.sql (see tests/test_event_types.py).
EVENT_TYPES = (
    "started",
    "cancelled",
    "submitted",
    "resolved",
    "clarification_requested",
    "clarified",
)

_CLARIFICATION_SELECT = """
    SELECT c.*, s.user_id, s.bug_text, s.suggestion_text
    FROM feedback_clarifications c
    JOIN feedback_submissions s ON s.id = c.feedback_submission_id
"""

_MESSAGE_ID_FIELDS = ("admin_message_id", "question_message_id", "reply_prompt_message_id")


class ClarificationError(Exception):
    """Raised when a clarification cannot be created or updated."""


class FeedbackService:
    """Service for storing and retrieving feedback submissions and events."""
    
    @staticmethod
    def store_submission(user_id: int, bug_text: str, suggestion_text: str) -> Optional[UUID]:
        """
        Store a completed feedback submission.
        
        Args:
            user_id: Telegram user ID
            bug_text: The bug/issue description
            suggestion_text: The suggested fix or new feature
            
        Returns:
            UUID of the stored submission, or None if storage failed
        """
        try:
            conn = get_connection()
            with closing(conn):
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO feedback_submissions (user_id, bug_text, suggestion_text)
                        VALUES (%s, %s, %s)
                        RETURNING id
                        """,
                        (user_id, bug_text, suggestion_text),
                    )
                    result = cur.fetchone()
                    submission_id = result[0] if result else None
                conn.commit()
            
            if submission_id:
                logger.info(f"✓ Feedback submission stored: user_id={user_id}, submission_id={submission_id}")
            return submission_id
        except Exception as e:
            logger.error(f"❌ Failed to store feedback submission: user_id={user_id}, error={str(e)}")
            return None
    
    @staticmethod
    def record_event(
        user_id: int,
        event_type: str,
        submission_id: Optional[UUID] = None,
    ) -> bool:
        """
        Record a feedback conversation event.
        
        Args:
            user_id: Telegram user ID
            event_type: One of EVENT_TYPES
            submission_id: Optional UUID of associated feedback submission
            
        Returns:
            True if event was recorded, False if storage failed
        """
        if event_type not in EVENT_TYPES:
            logger.warning(f"Unknown event type: {event_type}")
            return False
        
        try:
            conn = get_connection()
            with closing(conn):
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO feedback_events (user_id, event_type, feedback_submission_id)
                        VALUES (%s, %s, %s)
                        """,
                        (user_id, event_type, submission_id),
                    )
                conn.commit()
            
            logger.info(f"✓ Event recorded: user_id={user_id}, event_type={event_type}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to record event: user_id={user_id}, event_type={event_type}, error={str(e)}")
            return False
    
    @staticmethod
    def resolve_submission(submission_id: UUID) -> bool:
        """
        Mark a feedback submission as resolved by inserting a 'resolved' event.

        Args:
            submission_id: UUID of the submission to resolve

        Returns:
            True if the event was recorded, False on failure
        """
        try:
            conn = get_connection()
            with closing(conn):
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT user_id FROM feedback_submissions WHERE id = %s",
                        (submission_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        logger.warning(f"resolve_submission: no submission found for id={submission_id}")
                        return False
                    user_id = row[0]
                    cur.execute(
                        """
                        INSERT INTO feedback_events (user_id, event_type, feedback_submission_id)
                        VALUES (%s, 'resolved', %s)
                        """,
                        (user_id, submission_id),
                    )
                conn.commit()
            logger.info(f"✓ Submission resolved: submission_id={submission_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to resolve submission: submission_id={submission_id}, error={str(e)}")
            return False

    @staticmethod
    def get_unresolved_feedback(limit: int = 1) -> list[dict]:
        """
        Fetch the oldest feedback submissions that have no 'resolved' event.

        Args:
            limit: Maximum number of rows to return

        Returns:
            List of dicts with id, user_id, bug_text, suggestion_text, created_at
        """
        try:
            conn = get_connection()
            with closing(conn):
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT s.id, s.user_id, s.bug_text, s.suggestion_text, s.created_at
                        FROM feedback_submissions s
                        WHERE NOT EXISTS (
                            SELECT 1 FROM feedback_events e
                            WHERE e.feedback_submission_id = s.id
                              AND e.event_type = 'resolved'
                        )
                        ORDER BY s.created_at ASC
                        LIMIT %s
                        """,
                        (limit,),
                    )
                    rows = cur.fetchall()
            return [
                {
                    "id": r[0],
                    "user_id": r[1],
                    "bug_text": r[2],
                    "suggestion_text": r[3],
                    "created_at": r[4],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"❌ Failed to fetch unresolved feedback: {str(e)}")
            return []

    @staticmethod
    def is_resolved(submission_id: UUID) -> bool:
        """Return True if the submission has a 'resolved' event."""
        conn = get_connection()
        with closing(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM feedback_events
                    WHERE feedback_submission_id = %s AND event_type = 'resolved'
                    LIMIT 1
                    """,
                    (submission_id,),
                )
                return cur.fetchone() is not None

    @staticmethod
    def create_clarification(submission_id: UUID, question: str, options: list[str]) -> dict:
        """
        Create the single clarification for a submission in 'pending_approval' status.

        Raises:
            ClarificationError: submission missing, already resolved, or already has a clarification
        """
        conn = get_connection()
        with closing(conn):
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT id FROM feedback_submissions WHERE id = %s", (submission_id,))
                if cur.fetchone() is None:
                    raise ClarificationError(f"No submission found for id={submission_id}")
                cur.execute(
                    """
                    SELECT 1 FROM feedback_events
                    WHERE feedback_submission_id = %s AND event_type = 'resolved'
                    """,
                    (submission_id,),
                )
                if cur.fetchone() is not None:
                    raise ClarificationError(f"Submission {submission_id} is already resolved")
                try:
                    cur.execute(
                        """
                        INSERT INTO feedback_clarifications (feedback_submission_id, question, options)
                        VALUES (%s, %s, %s)
                        RETURNING id
                        """,
                        (submission_id, question, Jsonb(list(options))),
                    )
                except psycopg.errors.UniqueViolation as e:
                    raise ClarificationError(
                        f"Submission {submission_id} already has a clarification"
                    ) from e
                clarification_id = cur.fetchone()["id"]
            conn.commit()
        logger.info(f"✓ Clarification drafted: submission_id={submission_id}, clarification_id={clarification_id}")
        return FeedbackService.get_clarification(clarification_id)

    @staticmethod
    def get_clarification(clarification_id: UUID) -> Optional[dict]:
        """Fetch a clarification joined with its submission's user_id, bug_text and suggestion_text."""
        conn = get_connection()
        with closing(conn):
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(_CLARIFICATION_SELECT + " WHERE c.id = %s", (clarification_id,))
                return cur.fetchone()

    @staticmethod
    def get_clarification_by_submission(submission_id: UUID) -> Optional[dict]:
        """Fetch the clarification for a submission, if any."""
        conn = get_connection()
        with closing(conn):
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    _CLARIFICATION_SELECT + " WHERE c.feedback_submission_id = %s",
                    (submission_id,),
                )
                return cur.fetchone()

    @staticmethod
    def find_clarification_by_reply_prompt(user_id: int, message_id: int) -> Optional[dict]:
        """Find the clarification whose ForceReply prompt is message_id in user_id's chat."""
        conn = get_connection()
        with closing(conn):
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    _CLARIFICATION_SELECT
                    + " WHERE s.user_id = %s AND c.reply_prompt_message_id = %s",
                    (user_id, message_id),
                )
                return cur.fetchone()

    @staticmethod
    def _transition(clarification_id: UUID, from_status: str, set_sql: str, params: tuple) -> bool:
        """Apply an UPDATE only if the clarification is still in from_status. Returns True if applied."""
        conn = get_connection()
        with closing(conn):
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE feedback_clarifications SET {set_sql} WHERE id = %s AND status = %s",
                    (*params, clarification_id, from_status),
                )
                applied = cur.rowcount == 1
            conn.commit()
        return applied

    @staticmethod
    def mark_sent(clarification_id: UUID) -> bool:
        return FeedbackService._transition(
            clarification_id, "pending_approval", "status = 'sent', sent_at = now()", ()
        )

    @staticmethod
    def revert_to_pending(clarification_id: UUID) -> bool:
        return FeedbackService._transition(
            clarification_id, "sent", "status = 'pending_approval', sent_at = NULL", ()
        )

    @staticmethod
    def mark_discarded(clarification_id: UUID) -> bool:
        return FeedbackService._transition(
            clarification_id, "pending_approval", "status = 'discarded'", ()
        )

    @staticmethod
    def mark_answered(clarification_id: UUID, answer_text: str, answer_source: str) -> bool:
        return FeedbackService._transition(
            clarification_id,
            "sent",
            "status = 'answered', answer_text = %s, answer_source = %s, answered_at = now()",
            (answer_text, answer_source),
        )

    @staticmethod
    def set_message_id(clarification_id: UUID, field: str, message_id: int) -> None:
        """Store a Telegram message id (admin preview, question, or ForceReply prompt)."""
        if field not in _MESSAGE_ID_FIELDS:
            raise ValueError(f"Unknown message id field: {field}")
        conn = get_connection()
        with closing(conn):
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE feedback_clarifications SET {field} = %s WHERE id = %s",
                    (message_id, clarification_id),
                )
            conn.commit()

    @staticmethod
    def get_actionable_feedback() -> dict:
        """
        Return the planner's work queue.

        Actionable = not resolved and not waiting on the admin ('pending_approval')
        or the submitter ('sent'). Answered clarifications come first (oldest answer
        first), then everything else by submission age.

        Returns:
            {"actionable": [...], "pending_approval": int, "parked": int}
        """
        conn = get_connection()
        with closing(conn):
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT s.id, s.user_id, s.bug_text, s.suggestion_text, s.created_at,
                           c.status AS clarification_status, c.question AS clarification_question,
                           c.options AS clarification_options, c.answer_text AS clarification_answer,
                           c.answer_source AS clarification_answer_source, c.answered_at
                    FROM feedback_submissions s
                    LEFT JOIN feedback_clarifications c ON c.feedback_submission_id = s.id
                    WHERE NOT EXISTS (
                        SELECT 1 FROM feedback_events e
                        WHERE e.feedback_submission_id = s.id AND e.event_type = 'resolved'
                    )
                      AND (c.status IS NULL OR c.status IN ('answered', 'discarded'))
                    ORDER BY (c.status = 'answered') IS NOT TRUE,
                             c.answered_at ASC NULLS LAST,
                             s.created_at ASC
                    """
                )
                actionable = cur.fetchall()
                cur.execute(
                    """
                    SELECT c.status, COUNT(*) AS n
                    FROM feedback_clarifications c
                    WHERE c.status IN ('pending_approval', 'sent')
                      AND NOT EXISTS (
                          SELECT 1 FROM feedback_events e
                          WHERE e.feedback_submission_id = c.feedback_submission_id
                            AND e.event_type = 'resolved'
                      )
                    GROUP BY c.status
                    """
                )
                counts = {r["status"]: r["n"] for r in cur.fetchall()}
        return {
            "actionable": actionable,
            "pending_approval": counts.get("pending_approval", 0),
            "parked": counts.get("sent", 0),
        }

    @staticmethod
    def get_feedback(filters=None):
        """
        Retrieve stored feedback submissions (contract for future implementation).
        
        Args:
            filters: Optional dict with filtering criteria (not yet implemented)
            
        Raises:
            NotImplementedError: Retrieval feature will be added in a future sprint
        """
        raise NotImplementedError(
            "Feedback retrieval is not yet implemented. "
            "This method is reserved for future agent-driven queries and dashboards."
        )
