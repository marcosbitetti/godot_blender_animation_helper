# Godot Blender Animation Helper

This tool help users to produce cinematic animations providing a real time preview of model inside Godot Editor from Blender.

## Usage and Workflow

**first step:**

### Blender

1. install addon `Edit -> Preferences -> Add-ons` and load from disk: `addons/godot_blender_animation_helper/blender/rig-sync.py`
1. find `Rig Sync` on add-ons list and enable it
1. in 3D View open properties menu (shortcut: N)
1. find `Rig Sync` tab and enable it

**second step:**

### Godot

1. **o need** to enable plugins!
1. click on node that contains the desired `Skeleton3D`
1. click to add child node and find `BlenderRigSync` and add it
1. select it, and change `Skeleton name` if it needed
1. click enable
1. it make current model update they bones to same as in Blender editor

**third step:**

When you move bones on Blender it sync on Godot!

When end the task click to disable checkboxes on two editors.

*It can help you to integrate you animation on Godot from Blender*

*Video tutorial:* [youtube](http://lala)

## Extra Credits

- **Model**: Mysta Chibi
- **Author**: Macchimin (@Macchimin)
- **Source**: https://sketchfab.com/3d-models/mysta-chibi-2c3369ce9ac0484eb0795f2be3dc1f1b
- **License**: Creative Commons Attribution 4.0 International (CC BY 4.0) — https://creativecommons.org/licenses/by/4.0/

If you use this model or other third-party assets from this project, please follow the Creative Commons Attribution 4.0 license and the original author's attribution requirements.
