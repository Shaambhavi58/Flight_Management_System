from fastapi import APIRouter, Depends, HTTPException
from controllers.auth_controller import require_staff_or_admin, get_current_user
from services.alert_service import AlertService

router = APIRouter(prefix="/alerts", tags=["Alerts"])
alert_service = AlertService()

@router.get("")
def get_alerts(user: dict = Depends(require_staff_or_admin)):
    """Fetch all active operational alerts."""
    return alert_service.get_active_alerts()

@router.patch("/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int, user: dict = Depends(get_current_user)):
    success = alert_service.update_alert_status(alert_id, "Acknowledged", handled_by=user.get("username", "admin"))
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"success": True, "message": "Alert acknowledged"}

@router.patch("/{alert_id}/resolve")
def resolve_alert(alert_id: int, user: dict = Depends(get_current_user)):
    success = alert_service.update_alert_status(alert_id, "Resolved", handled_by=user.get("username", "admin"))
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"success": True, "message": "Alert resolved"}

@router.patch("/{alert_id}/dismiss")
def dismiss_alert(alert_id: int, user: dict = Depends(get_current_user)):
    success = alert_service.update_alert_status(alert_id, "Dismissed", handled_by=user.get("username", "admin"))
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"success": True, "message": "Alert dismissed"}
