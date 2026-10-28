import pytest

import main


@pytest.fixture
def production_env(monkeypatch):
    monkeypatch.setattr(main, "AUTH_REQUIRED", True)
    values = {
        "APP_ENV": "production",
        "DATABASE_URL": "postgresql://test:password@db.internal/nexus",
        "BETTER_AUTH_SECRET": "s" * 40,
        "REQUIRE_VERIFIED_EMAIL": "true",
        "ALLOWED_ORIGINS": "https://app.nexus.test",
        "ALLOWED_HOSTS": "api.nexus.test",
        "N8N_WEBHOOK_API_KEY": "integration-secret",
        "N8N_ORCHESTRATOR_URL": "https://automation.nexus.test/webhook/case",
        "PDF_SECURITY_URL": "https://pdf-safety.internal",
        "PDF_SECURITY_TOKEN": "p" * 40,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return monkeypatch


def test_valid_configuration_still_requires_vector_database(production_env):
    production_env.delenv("VECTOR_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="document database"):
        main._validate_production_configuration()


def test_reviewed_vector_store_and_valid_configuration_pass(production_env, monkeypatch):
    # Only models a future source-reviewed approval, not a runtime waiver.
    monkeypatch.setattr("db.vector_store.validate_production_vector_store", lambda: None)
    main._validate_production_configuration()


def test_node_env_cannot_disable_production_safeguards(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("NODE_ENV", "production")
    monkeypatch.setattr(main, "AUTH_REQUIRED", False)
    with pytest.raises(RuntimeError, match="AUTH_REQUIRED"):
        main._validate_production_configuration()


@pytest.mark.parametrize("key,value", [
    ("BETTER_AUTH_SECRET", "short"),
    ("REQUIRE_VERIFIED_EMAIL", "false"),
    ("ALLOWED_ORIGINS", "*"),
    ("ALLOWED_ORIGINS", "http://app.nexus.test"),
    ("ALLOWED_HOSTS", "localhost"),
    ("N8N_ORCHESTRATOR_URL", ""),
    ("PDF_SECURITY_URL", ""),
    ("PDF_SECURITY_TOKEN", "short"),
])
def test_production_fails_closed_on_missing_security_setting(production_env, key, value):
    production_env.setenv(key, value)
    with pytest.raises(RuntimeError):
        main._validate_production_configuration()
