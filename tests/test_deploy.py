import json
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_vercel_serves_the_finished_daily_page_instead_of_running_the_app():
    config = json.loads((ROOT / "vercel.json").read_text())
    assert config["framework"] is None
    assert config["outputDirectory"] == "public"
    assert "https://dhrupo.github.io/denguelinkbd/" in config["buildCommand"] and "public/index.html" in config["buildCommand"]


def test_vercel_never_publishes_a_page_that_has_no_forecast():
    assert """grep -q 'id="data"' public/index.html""" in json.loads((ROOT / "vercel.json").read_text())["buildCommand"]


def test_the_daily_job_tells_vercel_only_when_a_hook_has_been_set():
    workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text()
    assert "VERCEL_DEPLOY_HOOK: ${{ secrets.VERCEL_DEPLOY_HOOK }}" in workflow
    assert "if: env.VERCEL_DEPLOY_HOOK != ''" in workflow
    assert workflow.index("actions/deploy-pages") < workflow.index("VERCEL_DEPLOY_HOOK != ''")
