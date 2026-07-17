from dashboard.components import render_analytics_tab


def test_render_analytics_tab_is_available() -> None:
    assert callable(render_analytics_tab)
