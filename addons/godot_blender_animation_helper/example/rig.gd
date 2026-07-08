@tool
extends Node3D

const RIGHT_EYE := 18
const LEFT_EYE := 17
@onready var body := $rig/rig/Skeleton3D/Mysta_GEO

func _ready() -> void:
	_blink()

# just for fun!
func _blink() -> void:
	create_tween().tween_method(func(v : float) -> void:
		body.set_blend_shape_value(RIGHT_EYE, v)
		body.set_blend_shape_value(LEFT_EYE, v)
		, 0., 1., .25).finished.connect(func() -> void:
			create_tween().tween_method(func(v : float) -> void:
				body.set_blend_shape_value(RIGHT_EYE, v)
				body.set_blend_shape_value(LEFT_EYE, v)
				, 1., 0., .5).finished.connect(func() -> void:
					get_tree().create_timer(2. + randf_range(2.,6.)).timeout.connect(_blink)
					)
			)
