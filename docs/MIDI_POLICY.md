<!--
/**
* File name: MIDI_POLICY.md
* Brief: MGSC DAW 项目文档
* Function:
*     记录云端 DAW 服务接口、部署、状态或开发规范
* Author: 软件工程架构组
*     MGSC AI Software Architecture group
* Version: V2.5.10
* Date: 2026/04/30
*/
-->

# MIDI Policy Strategy

## Final Strategy

For VST rendering, the API style chooses the instrument and articulation, while the MIDI file supplies notes and performance expression.

That means a render request should be interpreted as:

```text
style_id = which instrument/articulation to use
midi = what to play
midi_policy = how to adapt the source MIDI to that style
```

For Kong Qin_RV styles, the service applies this policy before rendering:

```text
Remove Program Change
Remove Bank Select CC0/CC32
Keep Note On/Off and velocity
Keep expression controls: CC1, CC7, CC10, CC11, CC64
Keep Pitch Bend
Keep note aftertouch and channel pressure
Map the selected source channel to MIDI channel 1
```

When a source MIDI is multi-track, production clients should normally omit `midi_source_channel`. The service analyzes MIDI track names, program changes, and note statistics, then selects the likely melody channel. For the current `刀剑如梦.mid`, the track name `Melody: Flute` causes the service to auto-select MIDI channel 7.

```text
style_id=kong_gaohu_sus_leg_mw
```

`midi_source_channel` and `midi_target_channel` remain available as debug overrides. `midi_target_channel` should usually come from the selected style policy; Kong Qin_RV currently uses channel 1.

## Why Program Change Is Removed

In the old LMMS-style workflow, MIDI Program Change can be useful because the MIDI file may choose General MIDI instruments directly.

In this Carla + VST service, that conflicts with the API model. A `style_id` such as `kong_gaohu_sus_leg_mw` already means "load this exact Kong instrument/articulation state". If the MIDI file then sends Program Change or Bank Select, it can override or disturb the loaded plugin state. With Kong Qin_RV this can produce silence or the wrong sound.

So the API treats Program Change and Bank Select as arrangement metadata that should not control the plugin when a style is selected.

## Why Some Control Changes Are Kept

Control Change is not one thing. Some CC messages are part of musical expression:

```text
CC1 ModWheel: vibrato/expression in many instruments
CC7 Volume: track volume
CC10 Pan: stereo position
CC11 Expression: musical expression volume
CC64 Sustain: sustain pedal
```

Deleting all CC messages would make the output flatter and can differ from the intended performance. The first implementation therefore keeps the common expression controls and removes only the controls that are likely to switch instrument banks or produce unstable plugin behavior.

## Why This Will Differ From LMMS

LMMS may render a full MIDI arrangement by honoring MIDI program changes and routing tracks to built-in instruments or SoundFonts.

This service is intentionally different: it renders named VST styles. The stable production unit is not "whatever the MIDI asks for"; it is "this MIDI track played through this selected plugin state". That gives predictable API results and makes the Windows-to-Wine migration testable.

For full-arrangement rendering later, the service should split MIDI tracks into multiple style renders or route multiple plugins at once. For the current Kong single-instrument workflow, source-channel selection plus controlled MIDI cleanup is the safer path.
