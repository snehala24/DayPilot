from app.main import app, health_check, root


def test_health_check_endpoint():
    data = health_check()
    assert data["status"] == "healthy"
    assert data["service"] == "DayPilot"
    assert data["database"] == "connected"


def test_root_endpoint():
    data = root()
    assert data["name"] == "DayPilot API"
    assert "principles" in data
    assert "Proposal before action" in data["principles"]


def test_app_metadata_and_routes():
    assert app.title == "DayPilot API"
    assert app.version == "0.1.0"
    route_paths = [getattr(r, "path", None) for r in app.routes]
    assert "/health" in route_paths
    assert "/" in route_paths
