from files_organizer.calendar_sources.google_source import _extract_tag


def test_extract_tag_from_title():
    assert _extract_tag({"summary": "#Wakacje Wyjazd nad morze"}) == "Wakacje"


def test_extract_tag_from_description_when_missing_in_title():
    item = {"summary": "Wyjazd nad morze", "description": "notatki #Rodzina tutaj"}
    assert _extract_tag(item) == "Rodzina"


def test_extract_tag_missing_returns_none():
    assert _extract_tag({"summary": "Spotkanie", "description": "bez tagu"}) is None


def test_extract_tag_title_takes_priority_over_description():
    item = {"summary": "#Wakacje", "description": "#Rodzina"}
    assert _extract_tag(item) == "Wakacje"


def test_revoked_refresh_token_falls_back_to_browser_consent(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from google.auth.exceptions import RefreshError

    from files_organizer.calendar_sources.google_source import GoogleCalendarSource

    stale = MagicMock(valid=False, expired=True, refresh_token="old")
    stale.refresh.side_effect = RefreshError("invalid_grant")
    fresh = MagicMock(valid=True)
    fresh.to_json.return_value = '{"token": "new"}'
    flow = MagicMock()
    flow.run_local_server.return_value = fresh

    monkeypatch.setattr("google.oauth2.credentials.Credentials.from_authorized_user_file", lambda *a: stale)
    monkeypatch.setattr("google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file", lambda *a: flow)
    monkeypatch.setattr("googleapiclient.discovery.build", lambda *a, **kw: "service")

    token_file = tmp_path / "token.json"
    source = GoogleCalendarSource(credentials_file="credentials.json", token_file=str(token_file))

    assert source._build_service() == "service"
    flow.run_local_server.assert_called_once()
    assert token_file.read_text() == '{"token": "new"}'
