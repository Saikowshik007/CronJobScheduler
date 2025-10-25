"""Firebase Firestore manager for persistent storage."""
import os
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1 import FieldFilter

from models import CareerPage, Job, UserSettings

logger = logging.getLogger(__name__)


class FirebaseManager:
    """Manages Firebase Firestore operations."""

    def __init__(self, credentials_path: str):
        """Initialize Firebase connection."""
        try:
            cred = credentials.Certificate(credentials_path)
            firebase_admin.initialize_app(cred)
            self.db = firestore.client()
            logger.info("Firebase initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Firebase: {e}")
            raise

    # ===== Career Pages Operations =====

    def add_career_page(self, page: CareerPage) -> bool:
        """Add a new career page to monitor."""
        try:
            doc_ref = self.db.collection('career_pages').document(page.id)
            doc_ref.set(page.to_dict())
            logger.info(f"Added career page: {page.url}")
            return True
        except Exception as e:
            logger.error(f"Failed to add career page: {e}")
            return False

    def get_career_page(self, page_id: str) -> Optional[CareerPage]:
        """Get a specific career page by ID."""
        try:
            doc = self.db.collection('career_pages').document(page_id).get()
            if doc.exists:
                return CareerPage.from_dict(doc.to_dict())
            return None
        except Exception as e:
            logger.error(f"Failed to get career page: {e}")
            return None

    def get_all_career_pages(self) -> List[CareerPage]:
        """Get all career pages."""
        try:
            docs = self.db.collection('career_pages').stream()
            pages = []
            for doc in docs:
                pages.append(CareerPage.from_dict(doc.to_dict()))
            logger.info(f"Retrieved {len(pages)} career pages")
            return pages
        except Exception as e:
            logger.error(f"Failed to get career pages: {e}")
            return []

    def get_active_career_pages(self) -> List[CareerPage]:
        """Get all active career pages."""
        try:
            docs = self.db.collection('career_pages').where(
                filter=FieldFilter('status', '==', 'active')
            ).stream()
            pages = []
            for doc in docs:
                pages.append(CareerPage.from_dict(doc.to_dict()))
            logger.info(f"Retrieved {len(pages)} active career pages")
            return pages
        except Exception as e:
            logger.error(f"Failed to get active career pages: {e}")
            return []

    def get_pages_by_user(self, user_id: str) -> List[CareerPage]:
        """Get all career pages added by a specific user."""
        try:
            docs = self.db.collection('career_pages').where(
                filter=FieldFilter('added_by_user', '==', user_id)
            ).stream()
            pages = []
            for doc in docs:
                pages.append(CareerPage.from_dict(doc.to_dict()))
            return pages
        except Exception as e:
            logger.error(f"Failed to get pages by user: {e}")
            return []

    def update_career_page(self, page_id: str, updates: Dict[str, Any]) -> bool:
        """Update a career page."""
        try:
            doc_ref = self.db.collection('career_pages').document(page_id)
            doc_ref.update(updates)
            logger.info(f"Updated career page {page_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to update career page: {e}")
            return False

    def update_page_status(self, page_id: str, status: str) -> bool:
        """Update the status of a career page."""
        return self.update_career_page(page_id, {'status': status})

    def update_last_check(self, page_id: str, success: bool = True) -> bool:
        """Update the last check timestamp."""
        updates = {'last_check': firestore.SERVER_TIMESTAMP}
        if success:
            updates['last_success'] = firestore.SERVER_TIMESTAMP
            updates['error_count'] = 0
        else:
            # Increment error count
            doc = self.db.collection('career_pages').document(page_id).get()
            if doc.exists:
                current_error_count = doc.to_dict().get('error_count', 0)
                updates['error_count'] = current_error_count + 1

        return self.update_career_page(page_id, updates)

    def increment_jobs_found(self, page_id: str, count: int = 1) -> bool:
        """Increment the jobs found counter."""
        try:
            doc_ref = self.db.collection('career_pages').document(page_id)
            doc_ref.update({
                'jobs_found_total': firestore.Increment(count)
            })
            return True
        except Exception as e:
            logger.error(f"Failed to increment jobs found: {e}")
            return False

    def delete_career_page(self, page_id: str) -> bool:
        """Delete a career page."""
        try:
            self.db.collection('career_pages').document(page_id).delete()
            logger.info(f"Deleted career page {page_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete career page: {e}")
            return False

    # ===== Job History Operations =====

    def add_job_history(self, job: Job) -> bool:
        """Add a job to history (optional feature for analytics)."""
        try:
            doc_ref = self.db.collection('job_history').document(job.id)
            doc_ref.set(job.to_dict())
            logger.info(f"Added job to history: {job.title}")
            return True
        except Exception as e:
            logger.error(f"Failed to add job history: {e}")
            return False

    def get_jobs_by_page(self, page_id: str, limit: int = 50) -> List[Job]:
        """Get recent jobs for a specific page."""
        try:
            docs = self.db.collection('job_history').where(
                filter=FieldFilter('page_id', '==', page_id)
            ).order_by('first_seen', direction=firestore.Query.DESCENDING).limit(limit).stream()

            jobs = []
            for doc in docs:
                data = doc.to_dict()
                jobs.append(Job(**data))
            return jobs
        except Exception as e:
            logger.error(f"Failed to get jobs by page: {e}")
            return []

    # ===== User Settings Operations =====

    def get_user_settings(self, user_id: str) -> Optional[UserSettings]:
        """Get user settings."""
        try:
            doc = self.db.collection('user_settings').document(user_id).get()
            if doc.exists:
                return UserSettings.from_dict(doc.to_dict())
            # Return default settings if not found
            return UserSettings(telegram_user_id=user_id)
        except Exception as e:
            logger.error(f"Failed to get user settings: {e}")
            return UserSettings(telegram_user_id=user_id)

    def update_user_settings(self, settings: UserSettings) -> bool:
        """Update user settings."""
        try:
            doc_ref = self.db.collection('user_settings').document(settings.telegram_user_id)
            doc_ref.set(settings.to_dict())
            logger.info(f"Updated settings for user {settings.telegram_user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to update user settings: {e}")
            return False
