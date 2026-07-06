import bpy
from mathutils import Matrix

# Dicionário global para armazenar o último estado das matrizes dos bones
# Isso evita que o evento seja disparado continuamente mesmo se o bone estiver parado
_last_bone_matrices = {}

def meu_evento_bone_movido(bone_name, nova_matriz):
    """
    Este é o seu método/evento. Tudo o que você quiser fazer com a nova 
    matriz do bone (enviar para uma API, salvar em arquivo, etc.) deve começar aqui.
    """
    print(f"➔ [EVENTO] O bone '{bone_name}' mudou de posição!")
    print(f"Nova Matriz Mundial:\n{nova_matriz}\n")


@bpy.app.handlers.persistent
def checar_movimento_bone(scene, depsgraph):
    global _last_bone_matrices
    
    # Verifica se há um objeto ativo e se ele é uma Armature no modo de Pose
    obj = bpy.context.active_object
    if not obj or obj.type != 'ARMATURE' or obj.mode != 'POSE':
        return

    # Usamos o depsgraph para obter os dados avaliados em tempo real (incluindo constraints e IKs)
    obj_eval = obj.evaluated_get(depsgraph)
    matrix_world = obj_eval.matrix_world

    for pose_bone in obj_eval.pose.bones:
        # Calcula a matriz do bone no espaço do mundo (World Space)
        # Se preferir no espaço local da armature, use apenas: pose_bone.matrix
        world_matrix = matrix_world @ pose_bone.matrix
        
        bone_id = f"{obj.name}:{pose_bone.name}"
        
        # Se o bone já foi registrado antes, compara a matriz atual com a antiga
        if bone_id in _last_bone_matrices:
            if world_matrix != _last_bone_matrices[bone_id]:
                # A matriz mudou! Dispara o seu evento customizado
                meu_evento_bone_movido(pose_bone.name, world_matrix.copy())
        
        # Atualiza o dicionário com a matriz atual
        _last_bone_matrices[bone_id] = world_matrix.copy()


def register():
    # Limpa handlers antigos idênticos para evitar duplicidade ao rodar o script várias vezes
    unregister()
    
    # Adiciona o listener ao depsgraph (pós-atualização de dependências)
    bpy.app.handlers.depsgraph_update_post.append(checar_movimento_bone)
    print("Plugin de monitoramento de Bones ATIVADO.")

def unregister():
    # Remove o handler ao desativar o plugin
    if checar_movimento_bone in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(checar_movimento_bone)
    
    global _last_bone_matrices
    _last_bone_matrices.clear()
    print("Plugin de monitoramento de Bones DESATIVADO.")

if __name__ == "__main__":
    print("Iniciando o plugin de monitoramento de Bones...")
    register()
