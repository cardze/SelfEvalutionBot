"""Storage service for feedback submissions and events."""

import logging
from contextlib import closing
from uuid import UUID
from typing import Optional
from db import get_connection

logger = logging.getLogger(__name__)


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
            event_type: Type of event ('started', 'cancelled', 'submitted')
            submission_id: Optional UUID of associated feedback submission
            
        Returns:
            True if event was recorded, False if storage failed
        """
        if event_type not in ("started", "cancelled", "submitted", "resolved"):
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
