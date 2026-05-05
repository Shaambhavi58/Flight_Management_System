"""
Analytics Controller — Endpoints for the Operations Dashboard.
"""
from fastapi import APIRouter, Depends
from services.analytics_service import AnalyticsService
from controllers.auth_controller import require_staff_or_admin

router = APIRouter(prefix="/analytics", tags=["Analytics"])
analytics_service = AnalyticsService()

@router.get("/dashboard")
def get_dashboard_data(user: dict = Depends(require_staff_or_admin)):
    """
    Returns all data needed for the enterprise operations dashboard.
    Requires admin or staff role.
    """
    return {
        "kpis": analytics_service.get_kpis(),
        "status_distribution": analytics_service.get_status_distribution(),
        "airline_flights": analytics_service.get_flights_per_airline(),
        "airport_comparison": analytics_service.get_airport_comparison(),
        "live_alerts": analytics_service.get_live_alerts(),
        "batch_emails": analytics_service.get_batch_email_monitoring(),
    }
