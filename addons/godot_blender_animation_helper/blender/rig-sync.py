import bpy
from mathutils import Matrix
import threading
import http.server
import socket
import json
import urllib.parse
import time

bl_info = {
    "name": "Rig Sync",
    "author": "animation_helper",
    "version": (0, 1),
    "blender": (2, 80, 0),
    "location": "View3D > Sidebar > Rig Sync",
    "description": "Expose armature bone transforms via a local HTTP server and a simple N-panel toggle",
    "category": "Animation",
}

from bpy.props import BoolProperty, IntProperty

# Global dictionary to store the last known bone matrices.
# This prevents firing the update event continuously when a bone hasn't changed.
_last_bone_matrices = {}
_matrices_lock = threading.RLock()
_last_active_armature = None
_pending_updates = {}
# Condition variable used by request handlers to support long-poll waiting.
_pending_updates_cond = threading.Condition(_matrices_lock)
# Track clients (by IP) that already requested a full snapshot so that
# subsequent requests return only changes. Uses host IP to identify clients.
_seen_clients = set()

# HTTP server configuration
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8872
_server = None
_server_thread = None
LONGPOLL_DEFAULT_TIMEOUT = 5.0

# Use a server class that allows address reuse to avoid "address already in use" on restart
class _ReusableThreadingHTTPServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True

# Minimal debug toggle to avoid noisy logs in tight loops
DEBUG = False

def _debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)


def on_bone_moved(bone_name, new_matrix):
    """
    Event hook called when a bone transform changes.
    Extend this to send transforms to an API, write to a file, etc.
    """
    # Keep lightweight by default; enable DEBUG to see these logs.
    _debug_print(f"➔ [EVENT] Bone '{bone_name}' moved")
    _debug_print(f"World matrix:\n{new_matrix}\n")


@bpy.app.handlers.persistent
def check_bone_movement(scene, depsgraph):
    """
    Handler attached to `depsgraph_update_post` that inspects the active
    armature in Pose mode and records world-space bone matrices.
    When a bone's world matrix changes, `on_bone_moved` is triggered and
    a pending update is queued for HTTP clients.
    """
    global _last_bone_matrices, _last_active_armature, _pending_updates

    # Only operate when an armature is the active object and in Pose mode
    obj = bpy.context.active_object
    if not obj or obj.type != 'ARMATURE' or obj.mode != 'POSE':
        return

    # Use the evaluated object (includes constraints/IK) for accurate transforms
    obj_eval = obj.evaluated_get(depsgraph)
    matrix_world = obj_eval.matrix_world

    # store last active armature name (used by the /bones endpoint)
    armature_name = obj.name
    with _matrices_lock:
        _last_active_armature = armature_name

    for pose_bone in obj_eval.pose.bones:
        # Ignore bones explicitly marked as non-deforming (e.g. control bones)
        bone = getattr(pose_bone, "bone", None)
        deform = True
        if bone is not None:
            deform = getattr(bone, "use_deform", getattr(bone, "deform", True))
        if not deform:
            continue

        # Compute the bone matrix in world space. For armature-local matrices
        # use `pose_bone.matrix` instead.
        world_matrix = matrix_world @ pose_bone.matrix

        bone_id = f"{armature_name}:{pose_bone.name}"

        # Protect access to the shared dictionaries using a lock
        with _matrices_lock:
            prev = _last_bone_matrices.get(bone_id)
            if prev is not None:
                if world_matrix != prev:
                    # Matrix changed: trigger the event hook and queue update
                    on_bone_moved(pose_bone.name, world_matrix.copy())
                    _pending_updates[bone_id] = world_matrix.copy()
                    try:
                        # Notify any long-poll waiters that an update is available
                        with _pending_updates_cond:
                            _pending_updates_cond.notify_all()
                    except Exception:
                        pass

            # Update the cache with the current matrix
            _last_bone_matrices[bone_id] = world_matrix.copy()


class _BoneRequestHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path in ("/", "/status"):
                self._send_json({"status": "ok"})
            elif path in ("/bones", "/bones/"):
                # /bones supports long-poll semantics.
                # Behavior:
                # - When a new connection from a client arrives, return a full
                #   snapshot of eligible (deform) bones for the current armature.
                # - After that, the same client will receive only changed bones
                #   (long-poll). If a client's long-poll times out with no
                #   updates, the client is considered disconnected and the next
                #   connection will receive a full snapshot again.

                with _matrices_lock:
                    arm = _last_active_armature
                    # fallback: pick any armature seen if none recorded yet
                    if not arm:
                        arm_names = {k.split(":", 1)[0] for k in _last_bone_matrices.keys()} if _last_bone_matrices else set()
                        arm = next(iter(arm_names), None)

                prefix = f"{arm}:" if arm else None

                bones_list = []

                # Identify client by remote host IP (no query params allowed).
                client_host = None
                try:
                    client_host = self.client_address[0]
                except Exception:
                    client_host = None

                # If we have not yet given this client a full snapshot for its
                # current session, return a full list now and mark it seen.
                first_for_client = False
                with _matrices_lock:
                    if client_host and client_host not in _seen_clients:
                        first_for_client = True

                if first_for_client:
                    with _matrices_lock:
                        for k, v in _last_bone_matrices.items():
                            if prefix and not k.startswith(prefix):
                                continue
                            _, bone_name = k.split(":", 1)
                            bones_list.append({"name": bone_name, "tr": _serialize_matrix(v)})
                        if client_host:
                            _seen_clients.add(client_host)

                    response = {"armature_name": arm, "bones": bones_list}
                    self._send_json(response)
                    return

                # Normal mode: drain pending updates if any
                with _matrices_lock:
                    keys = [k for k in _pending_updates.keys() if not prefix or k.startswith(prefix)]
                    for k in keys:
                        v = _pending_updates.pop(k, None)
                        if v is not None:
                            _, bone_name = k.split(":", 1)
                            bones_list.append({"name": bone_name, "tr": _serialize_matrix(v)})

                # If none available, long-poll until timeout for updates
                timed_out = False
                if not bones_list:
                    deadline = time.time() + LONGPOLL_DEFAULT_TIMEOUT
                    with _pending_updates_cond:
                        while time.time() < deadline and not bones_list:
                            remaining = deadline - time.time()
                            _pending_updates_cond.wait(remaining)
                            keys = [k for k in _pending_updates.keys() if not prefix or k.startswith(prefix)]
                            for k in keys:
                                v = _pending_updates.pop(k, None)
                                if v is not None:
                                    _, bone_name = k.split(":", 1)
                                    bones_list.append({"name": bone_name, "tr": _serialize_matrix(v)})

                    if not bones_list:
                        timed_out = True

                response = {"armature_name": arm, "bones": bones_list}
                self._send_json(response)

                # If we timed out with no updates, consider the client's session
                # ended so the next connection is treated as a new one.
                if timed_out:
                    with _matrices_lock:
                        if client_host and client_host in _seen_clients:
                            _seen_clients.discard(client_host)
            else:
                self._send_json({"error": "not found"}, status=404)
        except Exception as e:
            self._send_json({"error": "server error", "detail": str(e)}, status=500)

    def _send_json(self, data, status=200):
        payload = json.dumps(data, default=_json_default).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            # Client disconnected while we were writing response. Treat this
            # as a session end: drop seen state so the next connection gets
            # a full snapshot.
            try:
                client_host = self.client_address[0]
                with _matrices_lock:
                    if client_host in _seen_clients:
                        _seen_clients.discard(client_host)
            except Exception:
                pass
            # Swallow socket errors - caller will detect connection closed.
        except Exception:
            # Re-raise unexpected exceptions to be handled by outer handler
            raise

    def log_message(self, format, *args):
        # Silence default logging
        return


def _json_default(obj):
    try:
        return _serialize_matrix(obj)
    except Exception:
        return str(obj)


def _serialize_matrix(matrix):
    # convert mathutils.Matrix (or nested sequences) to a flat list of floats (row-major)
    try:
        return [float(v) for row in matrix for v in row]
    except Exception:
        # fallback: try to coerce to nested lists then flatten
        try:
            lst = list(matrix)
            flat = []
            for row in lst:
                flat.extend([float(v) for v in row])
            return flat
        except Exception:
            return str(matrix)


def _capture_initial_bones():
    """
    Capture a snapshot of the currently active armature's deform bone world
    matrices into `_last_bone_matrices`. This provides an initial full
    snapshot for the first client that connects.
    """
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        obj = bpy.context.active_object
        if not obj or obj.type != 'ARMATURE' or obj.mode != 'POSE':
            return

        obj_eval = obj.evaluated_get(depsgraph)
        matrix_world = obj_eval.matrix_world
        armature_name = obj.name

        with _matrices_lock:
            for pose_bone in obj_eval.pose.bones:
                bone = getattr(pose_bone, "bone", None)
                deform = True
                if bone is not None:
                    deform = getattr(bone, "use_deform", getattr(bone, "deform", True))
                if not deform:
                    continue
                world_matrix = matrix_world @ pose_bone.matrix
                bone_id = f"{armature_name}:{pose_bone.name}"
                _last_bone_matrices[bone_id] = world_matrix.copy()
    except Exception as e:
        _debug_print("Failed to capture initial bones:", e)


def _start_server():
    global _server, _server_thread
    if _server is not None:
        _debug_print("HTTP server already running.")
        return
    try:
        server_address = (SERVER_HOST, SERVER_PORT)
        httpd = _ReusableThreadingHTTPServer(server_address, _BoneRequestHandler)
        httpd.daemon_threads = True
        _server = httpd
        _server_thread = threading.Thread(target=_server.serve_forever, name="RigSyncHTTPServer", daemon=True)
        _server_thread.start()
        _debug_print(f"RigSync HTTP server started at http://{SERVER_HOST}:{SERVER_PORT}/")
    except Exception as e:
        _debug_print("Failed to start HTTP server:", e)
        _server = None
        _server_thread = None


def _stop_server():
    global _server, _server_thread
    if _server is None:
        return
    try:
        _debug_print("Shutting down RigSync HTTP server...")
        # ask server to stop
        try:
            _server.shutdown()
        except Exception:
            pass

        # try to shutdown underlying socket to free the port immediately
        try:
            if hasattr(_server, 'socket') and _server.socket:
                _server.socket.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass

        try:
            _server.server_close()
        except Exception:
            pass

        # wait briefly for the server thread to exit
        if _server_thread:
            total_wait = 0.0
            timeout = 3.0
            interval = 0.05
            while _server_thread.is_alive() and total_wait < timeout:
                _server_thread.join(timeout=interval)
                total_wait += interval
                time.sleep(0)
            if _server_thread.is_alive():
                _debug_print("RigSync: server thread did not stop within timeout")
        # attempt to close socket descriptor to free port
        try:
            if hasattr(_server, 'socket') and _server.socket:
                _server.socket.close()
        except Exception:
            pass
    except Exception as e:
        _debug_print("Error stopping server:", e)
    finally:
        _server = None
        _server_thread = None
        _debug_print("RigSync HTTP server stopped.")


def start_rigsync_server():
    # ensure previous server state stopped to avoid duplicates
    stop_rigsync_server()

    # Attach the depsgraph handler (post update) and start the HTTP server
    try:
        # Capture a snapshot of current bones so the first client gets a full list
        _capture_initial_bones()
        bpy.app.handlers.depsgraph_update_post.append(check_bone_movement)
    except Exception as e:
        _debug_print("Warning: could not append handler:", e)

    # Start internal HTTP server
    _start_server()
    _debug_print("RigSync server ACTIVATED.")


def stop_rigsync_server():
    # Remove o handler ao desativar o plugin
    try:
        handlers = bpy.app.handlers.depsgraph_update_post
        # remove all occurrences to ensure handler is fully unregistered
        while check_bone_movement in handlers:
            handlers.remove(check_bone_movement)
    except Exception:
        pass

    # Stop internal HTTP server
    _stop_server()

    global _last_bone_matrices, _last_active_armature, _pending_updates
    with _matrices_lock:
        _last_bone_matrices.clear()
        _last_active_armature = None
        _pending_updates.clear()
        _seen_clients.clear()
    _debug_print("RigSync server DEACTIVATED.")


# UI integration: a simple checkbox in the N-panel to enable/disable the server
def _on_rig_sync_toggle(self, context):
    scene = context.scene
    if getattr(scene, "rig_sync_enabled", False):
        start_rigsync_server()
    else:
        stop_rigsync_server()


class RIGSYNC_PT_panel(bpy.types.Panel):
    bl_label = "Rig Sync"
    bl_idname = "RIGSYNC_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Rig Sync'

    def draw(self, context):
        layout = self.layout
        sc = context.scene
        layout.prop(sc, "rig_sync_enabled", text="Enable Rig Sync Server")


def register():
    bpy.utils.register_class(RIGSYNC_PT_panel)
    bpy.types.Scene.rig_sync_enabled = BoolProperty(
        name="Rig Sync Server",
        description="Run local server that exposes bone transforms",
        default=False,
        update=_on_rig_sync_toggle,
    )
    _debug_print("Rig Sync addon registered")


def unregister():
    # ensure server stopped before unregistering
    try:
        stop_rigsync_server()
    except Exception:
        pass
    try:
        del bpy.types.Scene.rig_sync_enabled
    except Exception:
        pass
    bpy.utils.unregister_class(RIGSYNC_PT_panel)
    _debug_print("Rig Sync addon unregistered")


if __name__ == "__main__":
    _debug_print("Starting RigSync addon (standalone run)")
    register()
