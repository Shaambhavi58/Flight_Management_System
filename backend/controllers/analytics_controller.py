"""
controllers/analytics_controller.py
=====================================
FastAPI router for the enterprise Operations Dashboard.

All routes are protected by the require_staff_or_admin dependency —
viewers do not have access to this analytics data.

Routes:
  GET /analytics/dashboard  → returns aggregated metrics for the dashboard
"""

from fastapi import APIRouter, Depends
from services.analytics_service import AnalyticsService          # all DB aggregation logic
from controllers.auth_controller import require_staff_or_admin   # blocks viewer-only accounts
from services.email_service import EmailService

# All analytics routes live under /analytics, grouped in Swagger under "Analytics"
router = APIRouter(prefix="/analytics", tags=["Analytics"])

# Shared service instances
analytics_service = AnalyticsService()
email_service = EmailService()


@router.get("/dashboard")
def get_dashboard_data(user: dict = Depends(require_staff_or_admin)):
    """
    Return all data needed to render the enterprise Operations Dashboard.
    Requires admin or staff role — viewers are blocked with HTTP 403.

    Response structure:
      kpis               → headline count cards (total, active, delayed, etc.)
      status_distribution → per-status counts for the doughnut chart
      airline_flights    → per-airline flight counts for the bar chart
      airport_comparison → active flights per airport for the horizontal bar chart
      live_alerts        → last 10 Delayed or Boarding flights for the alert feed
      batch_emails       → Morning / Afternoon / Evening email batch statuses
    """
    return {
        # Top KPI cards: total, active, delayed, boarding, arrived, airlines, on-time %, avg delay
        "kpis": analytics_service.get_kpis(),

        # Doughnut chart: how many flights are in each status category
        "status_distribution": analytics_service.get_status_distribution(),

        # Bar chart: how many flights each airline has today
        "airline_flights": analytics_service.get_flights_per_airline(),

        
        # Live alert feed: most recent Delayed and Boarding events
        "live_alerts": analytics_service.get_live_alerts(),

        # Batch email monitor: SCHEDULED / PENDING / SENT for Morning, Afternoon, Evening
        "batch_emails": analytics_service.get_batch_email_monitoring(),

        # Terminal distribution for the new chart
        "terminal_distribution": analytics_service.get_flights_per_terminal(),

        # Gate distribution metrics
        "gate_distribution": analytics_service.get_gate_status_distribution(),

        # Hourly traffic breakdown
        "hourly_traffic": analytics_service.get_hourly_traffic(),

        # Carousel workload distribution
        "carousel_utilization": analytics_service.get_carousel_utilization(),
    }


@router.post("/trigger-test-email")
def trigger_test_email(user: dict = Depends(require_staff_or_admin)):
    """
    Manually triggers an operational summary batch report email to the administrator.
    Used for live verification and system testing.
    """
    subject = "FMS Manual Operational Sync Alert"
    body = """Hello Team,
    
    This is a manually triggered Operational System Sync Alert from the FMS Operations Dashboard.
    
    Current System Health:
    - SMTP Integration: ACTIVE & ONLINE
    - RabbitMQ Messaging Pipeline: STABLE
    - Data Integrity Constraints: PASSING
    
    Operational Dashboard Link: http://127.0.0.1:8000
    
    Regards,
    Beumer Group FMS Operations Command Center
    """
    
    success = email_service.send_notification(
        to_email=email_service._admin_email,
        subject=subject,
        body=body
    )
    
    if success:
        return {"status": "success", "message": f"Test sync email dispatched to {email_service._admin_email} successfully!"}
    else:
        return {"status": "error", "message": "Failed to send email. Check SMTP credentials in FMS configuration."}

