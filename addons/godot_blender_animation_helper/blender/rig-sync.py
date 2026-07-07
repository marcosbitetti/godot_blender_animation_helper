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

# Dicionário global para armazenar o último estado das matrizes dos bones
# Isso evita que o evento seja disparado continuamente mesmo se o bone estiver parado
_last_bone_matrices = {}
_matrices_lock = threading.RLock()
_last_active_armature = None
_pending_updates = {}

# HTTP server configuration
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8872
_server = None
_server_thread = None

# Use a server class that allows address reuse to avoid "address already in use" on restart
class _ReusableThreadingHTTPServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True

# Minimal debug toggle to avoid noisy logs in tight loops
DEBUG = False

def _debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)


def meu_evento_bone_movido(bone_name, nova_matriz):
    """
    Este é o seu método/evento. Tudo o que quiser fazer com a nova 
    matriz do bone (enviar para uma API, salvar em arquivo, etc.) deve começar aqui.
    """
    # Avoid heavy prints in normal operation; enable DEBUG to see these logs
    _debug_print(f"➔ [EVENTO] O bone '{bone_name}' mudou de posição!")
    _debug_print(f"Nova Matriz Mundial:\n{nova_matriz}\n")


@bpy.app.handlers.persistent
def checar_movimento_bone(scene, depsgraph):
    global _last_bone_matrices, _last_active_armature, _pending_updates

    # Verifica se há um objeto ativo e se ele é uma Armature no modo de Pose
    obj = bpy.context.active_object
    if not obj or obj.type != 'ARMATURE' or obj.mode != 'POSE':
        return

    # Usamos o depsgraph para obter os dados avaliados em tempo real (incluindo constraints e IKs)
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

        # Calcula a matriz do bone no espaço do mundo (World Space)
        # Se preferir no espaço local da armature, use apenas: pose_bone.matrix
        world_matrix = matrix_world @ pose_bone.matrix

        bone_id = f"{armature_name}:{pose_bone.name}"

        # Protege acesso ao dicionário com um lock para a leitura via webserver
        with _matrices_lock:
            prev = _last_bone_matrices.get(bone_id)
            if prev is not None:
                if world_matrix != prev:
                    # A matriz mudou! Dispara o seu evento customizado
                    meu_evento_bone_movido(pose_bone.name, world_matrix.copy())
                    # armazena atualização pendente para o endpoint /bones (será consumida na leitura)
                    _pending_updates[bone_id] = world_matrix.copy()

            # Atualiza o dicionário com a matriz atual
            _last_bone_matrices[bone_id] = world_matrix.copy()


class _BoneRequestHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path in ("/", "/status"):
                self._send_json({"status": "ok"})
            elif path in ("/bones", "/bones/"):
                # Return and consume only the bones that were updated since last read.
                with _matrices_lock:
                    arm = _last_active_armature
                    # fallback: pick any armature seen if none recorded yet
                    if not arm:
                        arm_names = {k.split(":", 1)[0] for k in _last_bone_matrices.keys()} if _last_bone_matrices else set()
                        arm = next(iter(arm_names), None)

                    bones_list = []
                    if arm:
                        prefix = f"{arm}:"
                        # collect keys to pop to avoid modifying dict during iteration
                        keys = [k for k in _pending_updates.keys() if k.startswith(prefix)]
                        for k in keys:
                            v = _pending_updates.pop(k, None)
                            if v is not None:
                                _, bone_name = k.split(":", 1)
                                bones_list.append({"name": bone_name, "tr": _serialize_matrix(v)})

                response = {"armature_name": arm, "bones": bones_list}
                self._send_json(response)
            else:
                self._send_json({"error": "not found"}, status=404)
        except Exception as e:
            self._send_json({"error": "server error", "detail": str(e)}, status=500)

    def _send_json(self, data, status=200):
        payload = json.dumps(data, default=_json_default).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

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


def _start_server():
    global _server, _server_thread
    if _server is not None:
        print("HTTP server already running.")
        return
    try:
        server_address = (SERVER_HOST, SERVER_PORT)
        httpd = _ReusableThreadingHTTPServer(server_address, _BoneRequestHandler)
        httpd.daemon_threads = True
        _server = httpd
        _server_thread = threading.Thread(target=_server.serve_forever, name="RigSyncHTTPServer", daemon=True)
        _server_thread.start()
        print(f"RigSync HTTP server started at http://{SERVER_HOST}:{SERVER_PORT}/")
    except Exception as e:
        print("Failed to start HTTP server:", e)
        _server = None
        _server_thread = None


def _stop_server():
    global _server, _server_thread
    if _server is None:
        return
    try:
        print("Shutting down RigSync HTTP server...")
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
        print("Error stopping server:", e)
    finally:
        _server = None
        _server_thread = None
        print("RigSync HTTP server stopped.")


def start_rigsync_server():
    # ensure previous server state stopped to avoid duplicates
    stop_rigsync_server()

    # Adiciona o listener ao depsgraph (pós-atualização de dependências)
    try:
        bpy.app.handlers.depsgraph_update_post.append(checar_movimento_bone)
    except Exception as e:
        print("Warning: could not append handler:", e)

    # Start internal HTTP server
    _start_server()
    print("RigSync server ACTIVATED.")


def stop_rigsync_server():
    # Remove o handler ao desativar o plugin
    try:
        handlers = bpy.app.handlers.depsgraph_update_post
        # remove all occurrences to ensure handler is fully unregistered
        while checar_movimento_bone in handlers:
            handlers.remove(checar_movimento_bone)
    except Exception:
        pass

    # Stop internal HTTP server
    _stop_server()

    global _last_bone_matrices, _last_active_armature, _pending_updates
    with _matrices_lock:
        _last_bone_matrices.clear()
        _last_active_armature = None
        _pending_updates.clear()
    print("RigSync server DEACTIVATED.")


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
    print("Rig Sync addon registered")


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
    print("Rig Sync addon unregistered")


if __name__ == "__main__":
    print("Iniciando o plugin de monitoramento de Bones...")
    register()
