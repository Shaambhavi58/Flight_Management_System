from core.database import DatabaseManager
from models.models import OperationalAlertModel
from datetime import datetime
from typing import Optional

class AlertService:
    def __init__(self):
        self.db = DatabaseManager()

    def get_active_alerts(self) -> list:
        with self.db.session_scope() as session:
            alerts = session.query(OperationalAlertModel).filter(
                OperationalAlertModel.status.in_(["New", "Acknowledged"])
            ).order_by(OperationalAlertModel.id.desc()).limit(20).all()

            result = []
            for a in alerts:
                result.append({
                    "id": a.id,
                    "flight_id": a.flight_id,
                    "flight_number": a.flight_number,
                    "alert_type": a.alert_type,
                    "message": a.message,
                    "status": a.status,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
                    "metadata_json": a.metadata_json or {},
                    "handled_by": a.handled_by
                })
            return result

    def create_alert(self, flight_id: Optional[int], flight_number: Optional[str], alert_type: str, message: str, metadata_json: dict = None):
        with self.db.session_scope() as session:
            # Check for existing duplicate unresolved alert
            existing = session.query(OperationalAlertModel).filter(
                OperationalAlertModel.flight_id == flight_id,
                OperationalAlertModel.alert_type == alert_type,
                OperationalAlertModel.status.in_(["New", "Acknowledged"])
            ).first()

            if existing:
                # Update existing message/metadata in case it changed
                existing.message = message
                if metadata_json:
                    existing.metadata_json = metadata_json
                return existing.id

            new_alert = OperationalAlertModel(
                flight_id=flight_id,
                flight_number=flight_number,
                alert_type=alert_type,
                message=message,
                status="New",
                metadata_json=metadata_json
            )
            session.add(new_alert)
            session.flush()
            return new_alert.id

    def update_alert_status(self, alert_id: int, new_status: str, handled_by: str = None) -> bool:
        with self.db.session_scope() as session:
            alert = session.query(OperationalAlertModel).filter_by(id=alert_id).first()
            if not alert:
                return False

            alert.status = new_status
            if handled_by:
                alert.handled_by = handled_by

            now = datetime.utcnow()
            if new_status == "Acknowledged":
                alert.acknowledged_at = now
            elif new_status == "Resolved":
                alert.resolved_at = now
            elif new_status == "Dismissed":
                alert.dismissed_at = now

            return True
