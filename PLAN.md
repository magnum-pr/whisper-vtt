# Plan — Audio input device selection at startup

## Goal
On startup, if no audio input device has been configured, prompt the user to pick one from a numbered list. Save the choice to `config.toml` so it persists across restarts. If the saved device is missing, re-prompt.

## Approach
Add an `[audio] device_name = "<string>"` field to the TOML config (empty/unset = never configured / use default). Device is identified by its full name string for stability across USB plug/unplug events (indices shift; names don't). In `__main__.py`, after config loads and before creating `AudioCapture`, enumerate input devices via `sounddevice.query_devices()`. If no device is configured, display the list and accept a number. Save the selected device's name to `config.toml` so it persists. On subsequent launches, resolve the stored name to an index via exact match. If the stored device is no longer present, warn and re-prompt. Pass the resolved device index to `AudioCapture`, which forwards it to `sd.InputStream`.

## Phases

1. **Model + config** — Add `audio_device` field to `AppConfig`, `[audio]` TOML section, validation, serialization
2. **AudioCapture device parameter** — Accept optional `device` kwarg, pass to `sd.InputStream`
3. **Startup device prompt in `__main__.py`** — Enumerate, prompt, save, wire through

## Files that will change

| File | Change | Phase |
|---|---|---|
| `src/models.py` | Add `audio_device_name: Optional[str] = None` to `AppConfig` | 1 |
| `src/config_manager.py` | Add `_validate_audio_device_name()`, `[audio]` parsing in `load_config()`, `[audio]` section in `config_to_toml()` | 1 |
| `src/audio_capture.py` | Add `device_index: Optional[int] = None` to `__init__`, pass to `sd.InputStream` | 2 |
| `src/__main__.py` | Add `_resolve_audio_device()` helper (enumerate + prompt + resolve name→index), call after config load, pass to `AudioCapture()` | 3 |
| `tests/test_config_manager.py` | Test `_validate_audio_device_name`, roundtrip with audio_device_name | 1 |
| `tests/test_audio_capture.py` | Test device param stored, verify it's passed through | 2 |
| `tests/test_app_controller.py` | Update AppConfig fixtures to include audio_device_name=None | 3 |
| `config.toml` | Updated at runtime on first device selection (user's choice persisted) | 3 |

## Acceptance criteria

- [ ] On first run (no `[audio]` in config.toml), user sees numbered list of input devices and can select one
- [ ] Typing a number picks that device; Enter/0 uses system default
- [ ] Selection is saved by device name to `config.toml` and reused on next startup (no re-prompt)
- [ ] If saved device name no longer exists, app warns and re-prompts
- [ ] Device name resolves via exact match (no substring ambiguity)
- [ ] Selected device is passed through to `sd.InputStream`
- [ ] Audio capture with explicit device works (recording succeeds)
- [ ] All existing tests still pass (168+ tests)
- [ ] New tests cover config validation + roundtrip, AudioCapture device param, AppConfig fixture update

## Not in scope

- GUI device selector (this is a console app with tray icon)
- Changing device at runtime (tray menu item, hotkey)
- Device-specific sample rate or channel selection
- macOS device listing differences (`sounddevice` handles this transparently)

## Open questions

None

## References

None

## Current step

Complete — all phases done, 176/177 tests pass (1 pre-existing failure unrelated).

## Notes
