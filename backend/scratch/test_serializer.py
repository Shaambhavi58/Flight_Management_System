import sys
import os
sys.path.append(os.getcwd())

from models.schemas import FlightSerializer
from models.models import FlightModel, AirlineModel, AirportModel

class MockModel:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

mock_flight = MockModel(
    id=1,
    flight_number="6E101",
    airline=MockModel(code="6E", name="IndiGo"),
    airport_id=1,
    airport=MockModel(code="DEL"),
    origin="DEL",
    destination="BOM",
    departure_time="10:00",
    arrival_time="12:00",
    gate_number="G1",
    terminal_number="T1",
    status="Arrived",
    flight_type="arrival",
    carousel_number="C2"
)

result = FlightSerializer.orm_to_response(mock_flight)
print(result)
