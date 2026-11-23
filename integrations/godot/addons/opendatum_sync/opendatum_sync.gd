@tool
extends EditorPlugin
## OpenDatum Live Co-Editing Plugin for Godot 4.x
##
## Watches a project `.odir.json` Universal Spatial IR file for agent updates:
## - Non-locked nodes hot-update transforms & parametric dimensions automatically.
## - Nodes tagged `metadata/human_locked = true` are NEVER overwritten by agents.
## - Toolbar actions let designers lock any selected node and write manual tweaks
##   back to `.odir.json` so AI agents immediately see the updated human constraints.

var _watch_path: String = "res://scene.odir.json"
var _last_modified: int = 0
var _timer: Timer
var _toolbar_box: HBoxContainer


func _enter_tree() -> void:
	_toolbar_box = HBoxContainer.new()

	var btn_sync := Button.new()
	btn_sync.text = "OpenDatum: Pull USIR"
	btn_sync.pressed.connect(_pull_from_usir)
	_toolbar_box.add_child(btn_sync)

	var btn_lock := Button.new()
	btn_lock.text = "Lock & Push Edits"
	btn_lock.pressed.connect(_lock_selected_and_push_to_usir)
	_toolbar_box.add_child(btn_lock)

	add_control_to_container(CONTAINER_SPATIAL_EDITOR_MENU, _toolbar_box)

	_timer = Timer.new()
	_timer.wait_time = 1.0
	_timer.autostart = true
	_timer.timeout.connect(_poll_file_changes)
	add_child(_timer)


func _exit_tree() -> void:
	if _toolbar_box:
		remove_control_from_container(CONTAINER_SPATIAL_EDITOR_MENU, _toolbar_box)
		_toolbar_box.queue_free()
	if _timer:
		_timer.queue_free()


func set_usir_path(path: String) -> void:
	_watch_path = path
	_last_modified = 0


func _poll_file_changes() -> void:
	if not FileAccess.file_exists(_watch_path):
		return
	var mtime := FileAccess.get_modified_time(_watch_path)
	if mtime > _last_modified:
		_last_modified = mtime
		_pull_from_usir()


func _pull_from_usir() -> void:
	var root := get_editor_interface().get_edited_scene_root()
	if root == null or not FileAccess.file_exists(_watch_path):
		return

	var text := FileAccess.get_file_as_string(_watch_path)
	var parsed = JSON.parse_string(text)
	if typeof(parsed) != TYPE_DICTIONARY or not parsed.has("nodes"):
		push_warning("OpenDatum: Invalid USIR JSON at %s" % _watch_path)
		return

	var existing_by_id: Dictionary = {}
	for child in root.get_children():
		if child.has_meta("opendatum_id"):
			existing_by_id[str(child.get_meta("opendatum_id"))] = child

	var updated := 0
	var skipped_locked := 0

	for nd in parsed["nodes"]:
		var nid := str(nd.get("id", ""))
		if nid == "":
			continue
		if existing_by_id.has(nid):
			var node: Node3D = existing_by_id[nid]
			if node.has_meta("human_locked") and bool(node.get_meta("human_locked")):
				skipped_locked += 1
				continue
			_apply_node_transform(node, nd)
			updated += 1
		else:
			var body := StaticBody3D.new()
			body.name = str(nd.get("name", nid))
			body.set_meta("opendatum_id", nid)
			body.set_meta("discipline", str(nd.get("discipline", "generic")))
			body.set_meta("human_locked", bool(nd.get("provenance", {}).get("human_locked", false)))
			_apply_node_transform(body, nd)
			root.add_child(body)
			body.owner = root
			updated += 1

	print("OpenDatum Sync: updated=%d, preserved_human_locked=%d" % [updated, skipped_locked])


func _apply_node_transform(node: Node3D, nd: Dictionary) -> void:
	var tf: Dictionary = nd.get("transform", {})
	var pos: Array = tf.get("position", [0.0, 0.0, 0.0])
	var scl: Array = tf.get("scale", [1.0, 1.0, 1.0])
	node.position = Vector3(float(pos[0]), float(pos[1]), float(pos[2]))
	node.scale = Vector3(float(scl[0]), float(scl[1]), float(scl[2]))


func _lock_selected_and_push_to_usir() -> void:
	var sel := get_editor_interface().get_selection().get_selected_nodes()
	if sel.is_empty() or not FileAccess.file_exists(_watch_path):
		return

	var text := FileAccess.get_file_as_string(_watch_path)
	var doc = JSON.parse_string(text)
	if typeof(doc) != TYPE_DICTIONARY or not doc.has("nodes"):
		return

	var locked_ids: Dictionary = {}
	for n in sel:
		if n is Node3D and n.has_meta("opendatum_id"):
			n.set_meta("human_locked", true)
			locked_ids[str(n.get_meta("opendatum_id"))] = n

	for nd in doc["nodes"]:
		var nid := str(nd.get("id", ""))
		if locked_ids.has(nid):
			var gnode: Node3D = locked_ids[nid]
			nd["transform"]["position"] = [gnode.position.x, gnode.position.y, gnode.position.z]
			nd["transform"]["scale"] = [gnode.scale.x, gnode.scale.y, gnode.scale.z]
			if not nd.has("provenance"):
				nd["provenance"] = {}
			nd["provenance"]["human_locked"] = true

	var f := FileAccess.open(_watch_path, FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify(doc, "  "))
		f.close()
		_last_modified = FileAccess.get_modified_time(_watch_path)
		print("OpenDatum: Locked & pushed %d human-edited nodes to %s" % [locked_ids.size(), _watch_path])
