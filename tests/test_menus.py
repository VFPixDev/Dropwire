from src.handlers.menus import get_help_text, get_settings_hub_keyboard, get_settings_hub_text


def _callbacks(keyboard) -> list[str | None]:
    return [button.callback_data for row in keyboard.inline_keyboard for button in row]


def test_regular_user_settings_hide_global_and_private_profiles():
    text = get_settings_hub_text(is_private=True, is_admin=False)
    callbacks = _callbacks(get_settings_hub_keyboard(is_private=True, is_admin=False))

    assert "Глобальные" not in text
    assert "Личные" not in text
    assert "st:global" not in callbacks
    assert "st:dm" not in callbacks
    assert "st:groups" in callbacks
    assert "translate" in callbacks


def test_admin_keeps_global_settings_without_private_profile():
    text = get_settings_hub_text(is_private=True, is_admin=True)
    callbacks = _callbacks(get_settings_hub_keyboard(is_private=True, is_admin=True))

    assert "Глобальные" in text
    assert "st:global" in callbacks
    assert "st:dm" not in callbacks


def test_help_no_longer_advertises_status_command():
    assert "\n/status —" not in get_help_text()
