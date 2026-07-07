@tool
extends Node
class_name BlenderRigSync

@export var skeleton_name := "Skeleton3D" :
	set(name):
		skeleton_name = name
		_find_skel()
		update_configuration_warnings()
		
@export var enabled := false :
	set(v):
		enabled = v
		update_configuration_warnings()
		if enabled: _do_request()

@export_range(.15, 1., .05) var refresh_time : float = .25

var _connected := false
var _http : HTTPRequest
var _skeleton : Skeleton3D

func _ready() -> void:
	if not Engine.is_editor_hint(): return
	
	_find_skel()
	update_configuration_warnings()
	_http = HTTPRequest.new()
	add_child(_http)
	# Connect HTTPRequest signals for completion and timeout handling.
	if not _http.is_connected("request_completed", _on_http_request_completed):
		_http.connect("request_completed", _on_http_request_completed)
	#if not _http.is_connected("connection_timeout", _on_http_connection_timeout):
		#_http.connect("connection_timeout", _on_http_connection_timeout)
	
func _get_configuration_warnings() -> PackedStringArray:
	var warnings := PackedStringArray()
	if not enabled: return warnings
	
	if not _connected:
		warnings.append("Blender addon is not activated")
	
	if not _skeleton:
		warnings.append("Skeleton not found")
		
	return warnings

func _on_http_request_completed(result: int, response_code: int, headers: PackedStringArray, body: PackedByteArray) -> void:
	if not Engine.is_editor_hint(): return
	if not is_instance_valid(self): return
	
	_connected = response_code == HTTPClient.RESPONSE_OK
	update_configuration_warnings()
	if _skeleton:
		_apply_bones_from_body(body)

	if enabled:
		get_tree().create_timer(refresh_time).timeout.connect(_do_request)

func _on_http_connection_timeout() -> void:
	_connected = false
	update_configuration_warnings()

func _find_skel() -> void:
	_skeleton = get_parent().find_child(skeleton_name, true, false)

func _do_request() -> void:
	_http.request("http://127.0.0.1:8872/bones", PackedStringArray(),HTTPClient.METHOD_GET)

func _apply_bones_from_body(body: PackedByteArray) -> void:
	if body == null: return

	var body_text := body.get_string_from_utf8()
	var parse_result = JSON.parse_string(body_text)
	if parse_result == null:
		print("BlenderRigSync: failed to parse JSON body: %s" % parse_result.error_string)
		return

	var data : Dictionary = parse_result
	
	if not data.has("bones"): return

	var bones : Array = data["bones"]
	
	for item in bones:
		if typeof(item) != TYPE_DICTIONARY:
			continue
		var name := item.get("name", "") as String
		var m : = item.get("tr", null)  as Array
		if name == "" or tr == null:
			continue
		if typeof(m) != TYPE_ARRAY or m.size() < 12:
			continue

		# Expect a 4x4 matrix in row-major order (16 elements). Use first 12 values for basis+origin.
		var col0 := Vector3(m[0], m[4], m[8])
		var col1 := Vector3(m[1], m[5], m[9])
		var col2 := Vector3(m[2], m[6], m[10])
		var origin := Vector3(m[3], m[7], m[11])
		# Convert from Blender (Z-up) to Godot (Y-up) coordinate space.
		# Blender->Godot mapping: (x, y, z)_godot = (x, z, -y)_blender
		col0 = _blender_to_godot_vec3(col0)
		col1 = _blender_to_godot_vec3(col1)
		col2 = _blender_to_godot_vec3(col2)
		origin = _blender_to_godot_vec3(origin)

		var basis := Basis(col0, col1, col2)
		var transform := Transform3D(basis, origin)

		# Apply transform to skeleton if possible
		if _skeleton and _skeleton.has_method("find_bone") and _skeleton.has_method("set_bone_global_pose_override"):
			var idx := _skeleton.find_bone(name)
			if idx >= 0:
				_skeleton.set_bone_global_pose_override(idx, transform, 1.0, true)
		else:
			print("BlenderRigSync: parsed bone %s (no skeleton apply)" % name)

func _blender_to_godot_vec3(v: Vector3) -> Vector3:
	# Map Blender coordinates (X right, Y forward, Z up)
	# to Godot coordinates (X right, Y up, Z forward): (x, z, -y)
	return Vector3(v.x, v.z, -v.y)
