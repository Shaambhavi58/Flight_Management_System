from services.analytics_service import AnalyticsService
import os

# Mock DB if needed, but here we assume DB is running as uvicorn is running
service = AnalyticsService()

print("--- Testing Analytics KPI ---")
print(service.get_kpis())

print("\n--- Testing Status Distribution ---")
print(service.get_status_distribution())

print("\n--- Testing Flights per Airline ---")
print(service.get_flights_per_airline())

print("\n--- Testing Airport Comparison ---")
print(service.get_airport_comparison())
