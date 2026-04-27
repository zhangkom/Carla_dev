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
3. Connect `MIDI File events-out` to `Qin_RV events-in`.
4. Connect `Qin_RV output_1/output_2` to both `Audio Recorder input_1/input_2` and the playback outputs while debugging.
5. Open the Qin_RV UI, click `Browser`, select the instrument, click `LOAD`, then choose the preset.
6. Confirm sound with the on-screen keyboard or the MIDI file.
7. Save the Carla plugin state for the Qin_RV plugin as a `.carxs` file under `states\`.
8. Add or update a `styles` entry in `config\plugins.windows.example.json`.
9. Verify with `GET /v1/styles`, then render with `POST /v1/render` using `style_id`.

If a `LOAD` dialog is looking for `.fxp`, that is Kong's internal preset loader, not the Carla plugin-state export. For the service, prefer saving Carla `.carxs` state after the plugin is already configured and sounding correctly.

## Parameter Capture

Use the Carla parameter page to identify numeric parameters that can safely vary after the style is loaded. Record only parameters that produce predictable musical changes, such as volume, pan, expression-like controls, or simple effect amounts.

After the GUI confirms what a control does, dump Carla's parameter indexes:

```powershell
python tools\dump_plugin_parameters.py `
  --plugin-type vst2 `
  --plugin-path C:\VSTPlugins\KongAudio\Qin_RV_x64.DLL `
  --plugin-state states\kong_qinrv_gaohu_sus_leg_mw.carxs
```

Add stable defaults to a style:

```json
{
  "id": "kong_gaohu_sus_leg_mw",
  "plugin_id": "kong_qin_rv",
  "state": "states\\kong_qinrv_gaohu_sus_leg_mw.carxs",
  "parameters": [
    { "index": 7, "value": 0.8, "name": "example_volume" }
  ]
}
```

For temporary debugging, the render API also accepts `parameters_json`, but production clients should call named styles and business-level controls rather than raw plugin parameter indexes.
