# Godot Blender Animation Helper

This tool helps users produce cinematic animations by providing a real-time preview of a model inside the Godot Editor from Blender.

## Usage and Workflow

**First step:**

### Blender

**Recommended:** version 5.0+

1. Install the add-on (`Edit -> Preferences -> Add-ons`) and choose the "load from disk" option: `addons/godot_blender_animation_helper/blender/rig-sync.py`.
1. Find `Rig Sync` in the add-ons list and enable it.
1. In the 3D View, open the properties menu (shortcut: N).
1. Find the `Rig Sync` tab and enable it.

**Second step:**

### Godot

**Recommended:** version 4.5+

1. No need to enable plugins!
1. Click on the node that contains the desired `Skeleton3D`.
    * **Plus**: if your exported model has more than one `Skeleton3D`, you can hide the undesired node(s) to find the correct one.
1. Click to add a child node, find `BlenderRigSync`, and add it.
1. Select it, and change `Skeleton name` if needed.
1. Click Enable.
1. It makes the current model update its bones to match those in the Blender editor.

**Third step:**


When you move bones in Blender, the changes sync to Godot!

When the task is finished, click to disable the checkboxes in both editors.

*It can help you integrate your animation into Godot from Blender*

*Video tutorial:* [youtube](https://www.youtube.com/watch?v=C-myMbrMoDA)

## Credits

- **Maintainer**: Marcos Bitetti — GitHub: https://github.com/marcosbitetti — YouTube: https://www.youtube.com/@NerdOfTheMountain
- **Project License**: MIT License — see LICENSE or https://opensource.org/licenses/MIT

### Extra Credits

- **Model**: Mysta Chibi
- **Author**: Macchimin (@Macchimin)
- **Source**: https://sketchfab.com/3d-models/mysta-chibi-2c3369ce9ac0484eb0795f2be3dc1f1b
- **License**: Creative Commons Attribution 4.0 International (CC BY 4.0) — https://creativecommons.org/licenses/by/4.0/

If you use this model or other third-party assets from this project, please follow the Creative Commons Attribution 4.0 license and the original author's attribution requirements.
