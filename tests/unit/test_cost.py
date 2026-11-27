"""Unit tests for cost estimation logic."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from ark_mcp.tools._cost import (
    COST_PER_AUDIO_SECOND,
    COST_PER_IMAGE,
    COST_PER_VIDEO_TASK,
    COST_PER_VIDEO_TASK_2_5,
    DEFAULT_MAX_CONCURRENT,
    estimate_cost,
    image_cost_estimate,
    log_cost_estimate,
    price_source,
    register_video_cost_override,
)


class TestEstimateCostImage:
    """Tests for estimate_cost with image product."""

    def test_single_image(self) -> None:
        cost = estimate_cost(product="image", variations=1)
        assert cost == 0.03

    def test_multiple_images(self) -> None:
        cost = estimate_cost(product="image", variations=5)
        assert cost == round(5 * COST_PER_IMAGE, 2)

    def test_zero_variations_image(self) -> None:
        cost = estimate_cost(product="image", variations=0)
        assert cost == 0.0

    def test_large_count_images(self) -> None:
        cost = estimate_cost(product="image", variations=1000)
        assert cost == round(1000 * COST_PER_IMAGE, 2)

    def test_image_ignores_duration(self) -> None:
        cost = estimate_cost(product="image", variations=1, duration_seconds=30.0)
        assert cost == 0.03


class TestEstimateCostAudio:
    """Tests for estimate_cost with audio product."""

    def test_audio_with_duration_above_minimum(self) -> None:
        cost = estimate_cost(product="audio", variations=1, duration_seconds=30.0)
        assert cost == round(30 * COST_PER_AUDIO_SECOND, 2)

    def test_audio_clamps_to_minimum_duration(self) -> None:
        cost = estimate_cost(product="audio", variations=1, duration_seconds=5.0)
        assert cost == round(10 * COST_PER_AUDIO_SECOND, 2)

    def test_audio_clamps_zero_duration(self) -> None:
        cost = estimate_cost(product="audio", variations=1, duration_seconds=0.0)
        assert cost == round(10 * COST_PER_AUDIO_SECOND, 2)

    def test_audio_multiple_variations(self) -> None:
        cost = estimate_cost(product="audio", variations=3, duration_seconds=20.0)
        assert cost == round(3 * 20 * COST_PER_AUDIO_SECOND, 2)

    def test_audio_zero_variations(self) -> None:
        cost = estimate_cost(product="audio", variations=0, duration_seconds=30.0)
        assert cost == 0.0

    def test_audio_exactly_minimum_duration(self) -> None:
        cost = estimate_cost(product="audio", variations=1, duration_seconds=10.0)
        assert cost == round(10 * COST_PER_AUDIO_SECOND, 2)

    def test_audio_fractional_duration(self) -> None:
        cost = estimate_cost(product="audio", variations=1, duration_seconds=2.5)
        assert cost == round(10 * COST_PER_AUDIO_SECOND, 2)

    def test_audio_just_below_minimum(self) -> None:
        cost = estimate_cost(product="audio", variations=1, duration_seconds=9.9)
        assert cost == round(10 * COST_PER_AUDIO_SECOND, 2)

    def test_audio_large_duration(self) -> None:
        cost = estimate_cost(product="audio", variations=1, duration_seconds=3600.0)
        assert cost == round(3600 * COST_PER_AUDIO_SECOND, 2)


class TestEstimateCostVideo:
    """Tests for estimate_cost with video product."""

    def test_single_video_task(self) -> None:
        cost = estimate_cost(product="video", variations=1)
        assert cost == 0.07

    def test_multiple_video_tasks(self) -> None:
        cost = estimate_cost(product="video", variations=4)
        assert cost == round(4 * COST_PER_VIDEO_TASK, 2)

    def test_video_zero_variations(self) -> None:
        cost = estimate_cost(product="video", variations=0)
        assert cost == 0.0

    def test_video_ignores_duration(self) -> None:
        cost = estimate_cost(product="video", variations=1, duration_seconds=60.0)
        assert cost == 0.07

    def test_video_large_count(self) -> None:
        cost = estimate_cost(product="video", variations=500)
        assert cost == round(500 * COST_PER_VIDEO_TASK, 2)


class TestEstimateCostUnknown:
    """Tests for estimate_cost with unknown product."""

    def test_unknown_product_returns_zero(self) -> None:
        cost = estimate_cost(product="unknown", variations=10)
        assert cost == 0.0

    def test_unknown_product_with_duration_returns_zero(self) -> None:
        cost = estimate_cost(product="text", variations=5, duration_seconds=30.0)
        assert cost == 0.0

    def test_empty_product_returns_zero(self) -> None:
        cost = estimate_cost(product="", variations=1)
        assert cost == 0.0


class TestBuiltinEstimates:
    @pytest.mark.parametrize("model_id", [None, "dola-seedream-5-5-261028", "ep-custom-model"])
    @pytest.mark.parametrize("count", [0, 1, 1000])
    def test_image_estimate_without_family_keeps_flat_fallback(
        self, model_id: str | None, count: int
    ) -> None:
        assert image_cost_estimate(model_id, count) == (round(count * COST_PER_IMAGE, 4), "builtin")

    @pytest.mark.parametrize("product", ["image", "audio", "video"])
    @pytest.mark.parametrize("model_id", [None, "ep-custom-model"])
    def test_estimates_never_claim_account_pricing(
        self, product: str, model_id: str | None
    ) -> None:
        assert price_source(product, model_id) == "builtin"


class TestSeedream55Cost:
    @pytest.mark.parametrize(
        ("size", "output_cost"),
        [
            (None, 0.035),
            ("1K", 0.020),
            ("1.5K", 0.020),
            ("2K", 0.035),
            ("1800x1450", 0.020),  # 2.61M, inclusive lower tier.
            ("1801x1450", 0.035),
            ("2315x2000", 0.035),  # 4.63M, inclusive middle tier.
            ("2316x2000", 0.079),
            ("3840x2160", 0.079),
            ("2160x3840", 0.079),
            ("2880x2880", 0.079),
        ],
    )
    @pytest.mark.parametrize("count", [0, 1, 3])
    @pytest.mark.parametrize("references", [0, 1, 10])
    def test_pixel_tiers_and_repeated_reference_cost(
        self, size: str | None, output_cost: float, count: int, references: int
    ) -> None:
        expected = round(count * (output_cost + references * 0.008), 4)
        assert image_cost_estimate(
            "ep-image-test",
            count,
            family="seedream_5_5",
            size=size,
            reference_images=references,
        ) == (expected, "builtin")
        assert (
            estimate_cost(
                product="image",
                variations=count,
                model_id="ep-image-test",
                image_family="seedream_5_5",
                image_size=size,
                reference_images=references,
            )
            == expected
        )

    @pytest.mark.parametrize("family", [None, "seedream_pro", "seedream_lite", "seedream_4x"])
    def test_other_families_keep_flat_rate_even_with_55_model_id(self, family: str | None) -> None:
        assert image_cost_estimate(
            "dola-seedream-5-5-261028",
            2,
            family=family,
            size="3840x2160",
            reference_images=10,
        ) == (0.06, "builtin")

    def test_high_resolution_logging_uses_the_same_estimate(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        capsys.readouterr()
        cost = log_cost_estimate(
            product="image",
            variations=2,
            image_family="seedream_5_5",
            image_size="3840x2160",
            reference_images=1,
        )
        assert cost == 0.174
        assert json.loads(capsys.readouterr().err)["estimated_cost_usd"] == cost


class TestCostConstants:
    """Verify cost per unit values are reasonable."""

    def test_image_cost_is_positive(self) -> None:
        assert COST_PER_IMAGE > 0

    def test_audio_cost_per_second_is_positive(self) -> None:
        assert COST_PER_AUDIO_SECOND > 0

    def test_video_cost_is_positive(self) -> None:
        assert COST_PER_VIDEO_TASK > 0

    def test_video_more_expensive_than_image(self) -> None:
        assert COST_PER_VIDEO_TASK > COST_PER_IMAGE

    def test_default_max_concurrent_is_positive(self) -> None:
        assert DEFAULT_MAX_CONCURRENT > 0


class TestLogCostEstimate:
    """Tests for log_cost_estimate function."""

    def test_returns_same_cost_as_estimate_image(self, capsys: pytest.CaptureFixture[str]) -> None:
        cost = log_cost_estimate(product="image", variations=3)
        expected = estimate_cost(product="image", variations=3)
        assert cost == expected

    def test_returns_same_cost_as_estimate_audio(self, capsys: pytest.CaptureFixture[str]) -> None:
        cost = log_cost_estimate(product="audio", variations=2, duration_seconds=15.0)
        expected = estimate_cost(product="audio", variations=2, duration_seconds=15.0)
        assert cost == expected

    def test_returns_same_cost_as_estimate_video(self, capsys: pytest.CaptureFixture[str]) -> None:
        cost = log_cost_estimate(product="video", variations=5)
        expected = estimate_cost(product="video", variations=5)
        assert cost == expected

    def test_logs_cost_estimate_with_fields(self, capsys: pytest.CaptureFixture[str]) -> None:
        capsys.readouterr()
        log_cost_estimate(product="image", variations=2)
        captured = capsys.readouterr()
        record = json.loads(captured.err.strip())
        assert record["msg"] == "cost_estimate"
        assert record["product"] == "image"
        assert record["variations"] == 2
        assert record["estimated_cost_usd"] == round(2 * COST_PER_IMAGE, 2)

    def test_logs_audio_cost_with_duration(self, capsys: pytest.CaptureFixture[str]) -> None:
        capsys.readouterr()
        log_cost_estimate(product="audio", variations=3, duration_seconds=20.0)
        captured = capsys.readouterr()
        record = json.loads(captured.err.strip())
        assert record["msg"] == "cost_estimate"
        assert record["product"] == "audio"
        assert record["variations"] == 3
        assert record["estimated_cost_usd"] == round(3 * 20 * COST_PER_AUDIO_SECOND, 2)

    def test_logs_video_cost(self, capsys: pytest.CaptureFixture[str]) -> None:
        capsys.readouterr()
        log_cost_estimate(product="video", variations=2)
        captured = capsys.readouterr()
        record = json.loads(captured.err.strip())
        assert record["msg"] == "cost_estimate"
        assert record["product"] == "video"
        assert record["variations"] == 2
        assert record["estimated_cost_usd"] == round(2 * COST_PER_VIDEO_TASK, 2)

    def test_log_cost_estimate_calls_logger(self, capsys: pytest.CaptureFixture[str]) -> None:
        capsys.readouterr()
        with patch("ark_mcp.tools._cost.log_info") as mock_log:
            log_cost_estimate(product="image", variations=1)
            mock_log.assert_called_once_with(
                "cost_estimate",
                product="image",
                variations=1,
                estimated_cost_usd=0.03,
                price_source="builtin",
            )


class TestVideoCostByFamily:
    """Video pricing follows the registry family, not the model ID text."""

    @pytest.mark.parametrize("family", ["seedance_2_5", "seedance_2_5_flash"])
    def test_custom_2_5_endpoint_uses_static_2_5_fallback(self, family: str) -> None:
        cost = estimate_cost(
            product="video", variations=1, model_id="ep-my-endpoint", video_family=family
        )
        assert cost == COST_PER_VIDEO_TASK_2_5

    def test_2_5_variations_use_the_2_5_rate(self) -> None:
        cost = estimate_cost(product="video", variations=2, video_family="seedance_2_5")
        assert cost == round(2 * COST_PER_VIDEO_TASK_2_5, 2)

    def test_2_0_family_uses_default_price_even_with_2_5_looking_id(self) -> None:
        cost = estimate_cost(
            product="video",
            variations=1,
            model_id="dreamina-seedance-2-5-lookalike",
            video_family="seedance_2",
        )
        assert cost == COST_PER_VIDEO_TASK

    @pytest.mark.parametrize("family", ["seedance_2_5", "seedance_2_5_flash"])
    def test_model_override_wins_over_family(
        self, monkeypatch: pytest.MonkeyPatch, family: str
    ) -> None:
        monkeypatch.setattr("ark_mcp.tools._cost._VIDEO_COST_OVERRIDES", {})
        register_video_cost_override("ep-special", 1.23)
        cost = estimate_cost(
            product="video", variations=1, model_id="ep-special", video_family=family
        )
        assert cost == 1.23
