from snitchbot.sidecar.telegram_io.domain.services.topic_color_service import (
    TOPIC_COLOR_PALETTE,
    TopicColorService,
)


class TestTopicColorService:
    def test_palette_has_seven_telegram_preset_colors(self):
        assert TOPIC_COLOR_PALETTE == (
            7322096, 16766590, 13338331, 9367192, 16749490, 16478047, 7396918,
        )

    def test_color_for_service_is_deterministic(self):
        a1 = TopicColorService.color_for("orders-api")
        a2 = TopicColorService.color_for("orders-api")
        assert a1 == a2
        assert a1 in TOPIC_COLOR_PALETTE

    def test_different_services_distribute_across_palette(self):
        seen = {TopicColorService.color_for(f"svc-{i}") for i in range(50)}
        # We can't guarantee all 7 with 50 inputs, but >= 5 distinct is realistic.
        assert len(seen) >= 5
