"""Tests for the Phase 4 CLI runner (run.py)."""

from unittest.mock import MagicMock, patch, call

import pytest

import run  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_scraper(
    name: str = "mock",
    records_found: int = 100,
    records_matched: int = 5,
    records_new: int = 3,
    should_raise: bool = False,
    raise_msg: str | None = None,
):
    """Return a mock scraper class whose instances behave like real scrapers.

    All scrapers have the same interface:
    - __init__ accepts store, config, delay_seconds (at minimum)
    - scrape() takes no arguments, returns a stats dict
    - close() cleans up
    """
    instance = MagicMock()
    instance.name = name

    if should_raise:
        instance.scrape.side_effect = RuntimeError(raise_msg or f"{name} boom")
    else:
        instance.scrape.return_value = {
            "records_found": records_found,
            "records_matched": records_matched,
            "records_new": records_new,
        }

    cls = MagicMock(return_value=instance)
    return cls, instance


def _patch_load(scraper_map: dict):
    """Return a side_effect function for _load_scraper_class that returns
    the correct mock class for each scraper name."""
    def _loader(name):
        return scraper_map[name]
    return _loader


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRunScraperInterface:
    """All scrapers are constructed with store in __init__ and scrape() takes no args."""

    def test_scraper_constructed_with_store(self, tmp_path):
        mock_cls, mock_inst = _make_mock_scraper("canadabuys", 200, 10, 5)
        from lib.storage import OpportunityStore
        store = OpportunityStore(db_path=tmp_path / "test.db")

        with patch.object(run, "_load_scraper_class", return_value=mock_cls), \
             patch.object(run, "SCRAPER_CONFIGS", {"canadabuys": {"enabled": True, "extra": {"foo": 1}}}):
            run.run_scraper("canadabuys", store)

        # Verify constructor received store and config
        mock_cls.assert_called_once_with(store=store, config={"foo": 1}, delay_seconds=0)

    def test_scrape_called_with_no_args(self, tmp_path):
        mock_cls, mock_inst = _make_mock_scraper("bonfire", 50, 3, 1)
        from lib.storage import OpportunityStore
        store = OpportunityStore(db_path=tmp_path / "test.db")

        with patch.object(run, "_load_scraper_class", return_value=mock_cls), \
             patch.object(run, "SCRAPER_CONFIGS", {"bonfire": {"enabled": True, "extra": {}}}):
            run.run_scraper("bonfire", store)

        mock_inst.scrape.assert_called_once_with()

    def test_stats_read_from_return_value(self, tmp_path):
        mock_cls, mock_inst = _make_mock_scraper("canadabuys", 312, 8, 4)
        from lib.storage import OpportunityStore
        store = OpportunityStore(db_path=tmp_path / "test.db")

        with patch.object(run, "_load_scraper_class", return_value=mock_cls), \
             patch.object(run, "SCRAPER_CONFIGS", {"canadabuys": {"enabled": True, "extra": {}}}):
            stats = run.run_scraper("canadabuys", store)

        assert stats == {"records_found": 312, "records_matched": 8, "records_new": 4}

    def test_close_called_on_success(self, tmp_path):
        mock_cls, mock_inst = _make_mock_scraper("canadabuys", 100, 5, 2)
        from lib.storage import OpportunityStore
        store = OpportunityStore(db_path=tmp_path / "test.db")

        with patch.object(run, "_load_scraper_class", return_value=mock_cls), \
             patch.object(run, "SCRAPER_CONFIGS", {"canadabuys": {"enabled": True, "extra": {}}}):
            run.run_scraper("canadabuys", store)

        mock_inst.close.assert_called_once()

    def test_close_called_on_failure(self, tmp_path):
        mock_cls, mock_inst = _make_mock_scraper("canadabuys", should_raise=True)
        from lib.storage import OpportunityStore
        store = OpportunityStore(db_path=tmp_path / "test.db")

        with patch.object(run, "_load_scraper_class", return_value=mock_cls), \
             patch.object(run, "SCRAPER_CONFIGS", {"canadabuys": {"enabled": True, "extra": {}}}):
            with pytest.raises(RuntimeError):
                run.run_scraper("canadabuys", store)

        mock_inst.close.assert_called_once()


class TestOnceRunsEnabledScrapers:
    """--once should run all scrapers that are enabled in SCRAPER_CONFIGS."""

    def test_once_runs_enabled_scrapers(self, tmp_path):
        mock_cb_cls, mock_cb = _make_mock_scraper("canadabuys", 312, 8, 4)
        mock_bf_cls, mock_bf = _make_mock_scraper("bonfire", 50, 3, 1)
        mock_sk_cls, mock_sk = _make_mock_scraper("sasktenders", 40, 2, 1)

        loader_map = {
            "canadabuys": mock_cb_cls,
            "bonfire": mock_bf_cls,
            "sasktenders": mock_sk_cls,
        }

        configs = {
            "canadabuys": {"enabled": True, "extra": {}},
            "bonfire": {"enabled": True, "extra": {}},
            "sam_gov": {"enabled": False, "extra": {}},
            "sasktenders": {"enabled": True, "extra": {}},
        }

        with patch.object(run, "_load_scraper_class", side_effect=_patch_load(loader_map)), \
             patch.object(run, "SCRAPER_CONFIGS", configs), \
             patch.object(run, "DATA_DIR", tmp_path):
            exit_code = run.main(["--once"])

        assert exit_code == 0
        # All three enabled scrapers should have been instantiated.
        mock_cb_cls.assert_called_once()
        mock_bf_cls.assert_called_once()
        mock_sk_cls.assert_called_once()


class TestScraperFlag:
    """--scraper NAME should run only that one scraper."""

    def test_scraper_flag_runs_single(self, tmp_path):
        mock_cb_cls, mock_cb = _make_mock_scraper("canadabuys", 200, 10, 5)

        configs = {
            "canadabuys": {"enabled": True, "extra": {}},
            "bonfire": {"enabled": True, "extra": {}},
        }

        with patch.object(run, "_load_scraper_class", return_value=mock_cb_cls), \
             patch.object(run, "SCRAPER_CONFIGS", configs), \
             patch.object(run, "DATA_DIR", tmp_path):
            exit_code = run.main(["--scraper", "canadabuys"])

        assert exit_code == 0
        mock_cb_cls.assert_called_once()
        mock_cb.scrape.assert_called_once_with()


class TestDigestPlaceholder:
    """--digest should print placeholder message and exit 0."""

    def test_digest_placeholder(self, capsys):
        exit_code = run.main(["--digest"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "digest not implemented yet" in captured.out


class TestSlackPlaceholder:
    """--test-slack should print placeholder message and exit 0."""

    def test_slack_placeholder(self, capsys):
        exit_code = run.main(["--test-slack"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "slack not implemented yet" in captured.out


class TestExitCodeZeroOnSuccess:
    """Exit code should be 0 when all scrapers succeed."""

    def test_exit_code_zero_on_success(self, tmp_path):
        mock_cls, mock_inst = _make_mock_scraper("canadabuys", 100, 5, 2)

        configs = {
            "canadabuys": {"enabled": True, "extra": {}},
        }

        with patch.object(run, "_load_scraper_class", return_value=mock_cls), \
             patch.object(run, "SCRAPER_CONFIGS", configs), \
             patch.object(run, "DATA_DIR", tmp_path):
            exit_code = run.main(["--once"])

        assert exit_code == 0


class TestExitCodeOneOnFailure:
    """Exit code should be 1 when any scraper fails, but all others still run."""

    def test_exit_code_one_on_failure(self, tmp_path):
        mock_cb_cls, mock_cb = _make_mock_scraper("canadabuys", should_raise=True)
        mock_bf_cls, mock_bf = _make_mock_scraper("bonfire", 50, 3, 1)

        loader_map = {
            "canadabuys": mock_cb_cls,
            "bonfire": mock_bf_cls,
        }

        configs = {
            "canadabuys": {"enabled": True, "extra": {}},
            "bonfire": {"enabled": True, "extra": {}},
        }

        with patch.object(run, "_load_scraper_class", side_effect=_patch_load(loader_map)), \
             patch.object(run, "SCRAPER_CONFIGS", configs), \
             patch.object(run, "DATA_DIR", tmp_path), \
             patch.dict(run.SCRAPER_MAP, {
                 "canadabuys": ("scrapers.canadabuys", "CanadaBuysScraper"),
                 "bonfire": ("scrapers.bonfire", "BonfireScraper"),
             }, clear=True):
            exit_code = run.main(["--once"])

        assert exit_code == 1
        # Both scrapers should still have been instantiated (runner continues).
        mock_cb_cls.assert_called_once()
        mock_bf_cls.assert_called_once()
        # Bonfire should have had scrape() called despite canadabuys failing.
        mock_bf.scrape.assert_called_once()


class TestDisabledScraperSkipped:
    """sam_gov (disabled in config) should be skipped with --once."""

    def test_disabled_scraper_skipped(self, tmp_path):
        mock_cb_cls, mock_cb = _make_mock_scraper("canadabuys", 100, 5, 2)
        mock_sam_cls, mock_sam = _make_mock_scraper("sam_gov", 200, 10, 5)

        loader_map = {
            "canadabuys": mock_cb_cls,
        }

        configs = {
            "canadabuys": {"enabled": True, "extra": {}},
            "sam_gov": {"enabled": False, "extra": {}},
        }

        with patch.object(run, "_load_scraper_class", side_effect=_patch_load(loader_map)), \
             patch.object(run, "SCRAPER_CONFIGS", configs), \
             patch.object(run, "DATA_DIR", tmp_path):
            exit_code = run.main(["--once"])

        assert exit_code == 0
        # Only canadabuys should have been instantiated.
        mock_cb_cls.assert_called_once()
        # sam_gov should never have been touched.
        mock_sam_cls.assert_not_called()


class TestTotalMatchedInOutput:
    """total_matched should appear in the totals log line."""

    def test_total_matched_logged(self, tmp_path, caplog):
        mock_cb_cls, _ = _make_mock_scraper("canadabuys", 100, 7, 2)
        mock_bf_cls, _ = _make_mock_scraper("bonfire", 50, 3, 1)

        loader_map = {
            "canadabuys": mock_cb_cls,
            "bonfire": mock_bf_cls,
        }

        configs = {
            "canadabuys": {"enabled": True, "extra": {}},
            "bonfire": {"enabled": True, "extra": {}},
        }

        import logging
        with caplog.at_level(logging.INFO), \
             patch.object(run, "_load_scraper_class", side_effect=_patch_load(loader_map)), \
             patch.object(run, "SCRAPER_CONFIGS", configs), \
             patch.object(run, "DATA_DIR", tmp_path):
            run.main(["--once"])

        # Find the totals log line and verify it contains matched count
        totals_lines = [r.message for r in caplog.records if "Totals:" in r.message]
        assert len(totals_lines) == 1
        assert "10 matched" in totals_lines[0]  # 7 + 3 = 10


class TestApiKeySanitization:
    """Exception messages containing API keys should be sanitized before logging."""

    def test_api_key_scrubbed_from_error_log(self, tmp_path, caplog):
        secret_key = "super_secret_key_12345"
        mock_cls, mock_inst = _make_mock_scraper(
            "sam_gov",
            should_raise=True,
            raise_msg=f"HTTP 403 at https://api.sam.gov/v2/search?api_key={secret_key}&ncode=541512",
        )

        configs = {
            "sam_gov": {"enabled": True, "extra": {}},
        }

        import logging
        with caplog.at_level(logging.ERROR), \
             patch.object(run, "_load_scraper_class", return_value=mock_cls), \
             patch.object(run, "SCRAPER_CONFIGS", configs), \
             patch.object(run, "DATA_DIR", tmp_path):
            exit_code = run.main(["--scraper", "sam_gov"])

        assert exit_code == 1
        # The secret key should NOT appear anywhere in the log
        full_log = " ".join(r.message for r in caplog.records)
        assert secret_key not in full_log
        assert "***REDACTED***" in full_log


class TestSetupDirsCalled:
    """main() should call config.setup_dirs() at startup."""

    def test_setup_dirs_called(self, capsys):
        with patch.object(run.config, "setup_dirs") as mock_setup:
            # Use --digest to avoid needing scraper mocks
            run.main(["--digest"])

        mock_setup.assert_called_once()
