import importlib


def test_dashboard_components_expose_expected_tabs() -> None:
    components = importlib.import_module("dashboard.components")
    assert callable(getattr(components, "render_analytics_tab"))
    assert callable(getattr(components, "render_zones_tab"))
    assert callable(getattr(components, "render_settings_tab"))
