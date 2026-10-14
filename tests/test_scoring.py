"""Tests for scoring helpers: engagement normalization and email escaping."""
from datetime import date

import pytest

from xscimon.services.scoring import _normalise_engagement
from xscimon.services.email import _render_email


def test_engagement_log_scale():
    assert _normalise_engagement(0) == 0.0
    assert _normalise_engagement(10_000) == 1.0
    assert _normalise_engagement(1_000_000) == 1.0  # capped
    # Log scale discriminates in the realistic range for research accounts.
    assert _normalise_engagement(100) == pytest.approx(0.50, abs=0.01)
    assert _normalise_engagement(1000) == pytest.approx(0.75, abs=0.01)
    # Strictly increasing below the cap.
    assert _normalise_engagement(10) < _normalise_engagement(100) < _normalise_engagement(1000)


def test_email_escapes_post_content():
    domains = [{
        "domain_name": "Bio <b>Lab</b>",
        "status": "complete",
        "posts": [{
            "author_handle": "evil<script>",
            "created_at": "2026-07-15T09:00:00+00:00",
            "text": 'New paper! <img src=x onerror="alert(1)"> & more',
        }],
    }]
    html_out = _render_email(date(2026, 7, 15), domains)

    assert "<script>" not in html_out
    assert "<img" not in html_out
    assert "&lt;script&gt;" in html_out
    assert "&amp; more" in html_out
    assert "Bio &lt;b&gt;Lab&lt;/b&gt;" in html_out
