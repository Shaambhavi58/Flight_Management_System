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

# All analytics routes live under /analytics, grouped in Swagger under "Analytics"
router = APIRouter(prefix="/analytics", tags=["Analytics"])

# Shared service instance — single connection pool for all analytics queries
analytics_service = AnalyticsService()


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
        # Top KPI cards: total, active, delayed, boarding, arrived, airlines
        "kpis": analytics_service.get_kpis(),

        # Doughnut chart: how many flights are in each status category
        "status_distribution": analytics_service.get_status_distribution(),

        # Bar chart: how many flights each airline has today
        "airline_flights": analytics_service.get_flights_per_airline(),

        # Horizontal bar: which airports have the most active traffic right now
        "airport_comparison": analytics_service.get_airport_comparison(),

        # Live alert feed: most recent Delayed and Boarding events
        "live_alerts": analytics_service.get_live_alerts(),

        # Batch email monitor: SCHEDULED / PENDING / SENT for Morning, Afternoon, Evening
        "batch_emails": analytics_service.get_batch_email_monitoring(),
    }
