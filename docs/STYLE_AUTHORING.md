# Style Authoring With Carla GUI

The production path will be headless, but the GUI is the right tool for discovering and freezing plugin behavior.

## What Becomes an API Control

Use three layers:

1. `style_id`: the main API control. It maps to a plugin plus a Carla `.carxs` state file saved from the GUI.
2. `parameters`: optional Carla parameter index/value overrides for small, safe variations after a state is loaded.
3. MIDI controls: velocity, channel, mod wheel, pitch bend, program changes, and key switches should stay in the MIDI file or a future MIDI preprocessing layer.

For Kong Qin_RV, instrument selection, preset selection, library paths, layers, and channel/output setup should normally be saved into a `.carxs` state and called by `style_id`. Do not rely on the API to click Kong's browser or import instruments at render time.

## Kong Qin_RV Workflow

1. Start Carla with `run_carla_gui.bat`.
2. Add `MIDI File`, `Qin_RV`, and `Audio Recorder`.
   Add Qin_RV from `C:\VSTPlugins\KongAudio\Qin_RV_x64.DLL`; do not use copied installer payload DLLs from `mgsc_daw_assets`.
3. Connect `MIDI File events-out` to `Qin_RV events-in`.
4. Connect `Qin_RV output_1/output_2` to both `Audio Recorder input_1/input_2` and the playback outputs while debugging.
5. Open the Qin_RV UI from Carla's gear icon, select the instrument and articulation, and confirm the bottom keyboard plays the expected sound.
6. Confirm sound with the on-screen keyboard or the MIDI file.
7. Use Carla's wrench/edit page for the Qin_RV plugin to save the plugin state as a `.carxs` file under `states\`.
8. Add or update a `styles` entry in `config\plugins.windows.example.json`.
9. Verify with `GET /v1/styles`, then render with `POST /v1/render` using `style_id`.

If a `LOAD` dialog is looking for `.fxp`, that is Kong's internal preset loader, not the Carla plugin-state export. For the service, prefer saving Carla `.carxs` state after the plugin is already configured and sounding correctly.

Use `GET /v1/styles` after saving. If `state_binary_matches_plugin` is `false`, the `.carxs` was saved from the wrong DLL path and should be recreated from the configured plugin DLL.

The first GaoHu states currently use this naming convention:

```text
kong_gaohu_sus_leg_mw.carxs
kong_gaohu_stac_1.carxs
kong_gaohu_trill.carxs
kong_gaohu_tremolo.carxs
```

## Parameter Capture

Use the Carla parameter page to identify numeric parameters that can safely vary after the style is loaded. Record only parameters that produce predictable musical changes, such as volume, pan, expression-like controls, or simple effect amounts.

After the GUI confirms what a control does, dump Carla's parameter indexes:

```powershell
python tools\dump_plugin_parameters.py `
  --plugin-type vst2 `
  --plugin-path C:\VSTPlugins\KongAudio\Qin_RV_x64.DLL `
  --plugin-state states\kong_gaohu_sus_leg_mw.carxs
```

Add stable defaults to a style:

```json
{
  "id": "kong_gaohu_sus_leg_mw",
  "plugin_id": "kong_qin_rv",
  "instrument": "ChineeGaoHu",
  "articulation": "Sus_Leg_1_MW",
  "state": "states\\kong_gaohu_sus_leg_mw.carxs",
  "parameters": [
    { "index": 7, "value": 0.8, "name": "example_volume" }
  ]
}
```

For temporary debugging, the render API also accepts `parameters_json`, but production clients should call named styles and business-level controls rather than raw plugin parameter indexes.

## MIDI Policy

Kong styles use a MIDI cleanup policy before rendering. The style state chooses the instrument/articulation, so MIDI Program Change and Bank Select are removed to prevent the MIDI file from overriding the selected Kong sound.

Expression controls are not removed by default. The service keeps velocity, Pitch Bend, CC1, CC7, CC10, CC11, and CC64 so the performance does not become unnecessarily flat.

For multi-track MIDI files, pass the musical source channel during rendering. For the current `刀剑如梦.mid`, the melody is channel 7:

```powershell
curl.exe -X POST http://127.0.0.1:8000/v1/render `
  -F "style_id=kong_gaohu_sus_leg_mw" `
  -F "midi_source_channel=7" `
  -F "midi=@C:\work\workspace_own\workspace_carla\midi\刀剑如梦.mid"
```

See `docs\MIDI_POLICY.md` for the full strategy and rationale.
