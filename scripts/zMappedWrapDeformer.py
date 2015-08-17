import maya.cmds as cmds
import maya.OpenMaya as OpenMaya
import maya.OpenMayaAnim as OpenMayaAnim
import math, time

def _getShape(node):
    """
    Returns a shape node from a given transform or shape.
    """
    if cmds.nodeType(node) == 'transform':
        shapes = cmds.listRelatives(node, shapes=True, path=True)
        if not shapes:
            raise RuntimeError, '%s has no shape' % node
        return shapes[0]
    elif cmds.nodeType(node) in ['mesh', 'nurbsCurve', 'nurbsSurface']:
        return node

def _find_visible_shape(transform):
    # If this is already a mesh, just use it.
    if cmds.nodeType(transform) == 'mesh':
        return transform

    shapes = cmds.listRelatives(transform, children=True, shapes=True, path=True) or []
    for s in shapes:
        if cmds.getAttr('%s.intermediateObject' % s):
            continue
        return s
    raise RuntimeError('No visible shape found for %s.' % transform)

def _find_deformer(node, nodeType):
    """
    Find a deformer from a node associated with it.
    """
    if cmds.nodeType(node) == 'transform':
        node = _find_visible_shape(node)

    if cmds.nodeType(node) == nodeType:
        return node

    if cmds.nodeType(node) == 'mesh':
        # Look for the deformer in the mesh's history.
        for history_node in cmds.listHistory(node, gl=True, pdo=True) or []:
            if nodeType in cmds.nodeType(history_node, inherited=True):
                return history_node

    return None

def _load_plugin():
    if not cmds.pluginInfo('zMappedWrapDeformer.py', query=True, loaded=True):
        cmds.loadPlugin('zMappedWrapDeformer.py')

def _findDeformerInput(deformer):
    outputGeometry = cmds.listConnections('%s.outputGeometry[0]' % deformer) or []
    if not outputGeometry:
        raise RuntimeError('Couldn\'t find the input mesh for %s.' % deformer)

    history_nodes = cmds.listHistory(outputGeometry[0])

    for history_node in history_nodes:
        if cmds.nodeType(history_node) != 'mesh':
            continue
        return history_node

    raise RuntimeError('Couldn\'t find the input mesh for %s.' % deformer)

def _getNextAvailableIndex(deformer):
    existingIndexes = cmds.getAttr('%s.inputTarget' % deformer, mi=True) or [-1]
    return max(existingIndexes) + 1
    
def create(mesh=None):
    _load_plugin()
    if mesh is None:
        sel = cmds.ls(sl=True, l=True)
        if not sel or len(sel) != 1:
            OpenMaya.MGlobal.displayError('Select a mesh.')
            return
        mesh = sel[0]

    return cmds.deformer(mesh, type='zMappedWrapDeformer')[0]

def addTarget(deformer=None, targetShape=None, tolerance=0.001):
    """
    Add a target to a zMappedWrapDeformer.
    """
    _load_plugin()
    
    if deformer is None or targetShape is None:
        sel = cmds.ls(sl=True, l=True)
        if not sel or len(sel) != 2:
            OpenMaya.MGlobal.displayError('Select a target object and then the base object.')
            return
        targetShape = sel[0]
        deformer = sel[1]
   
    deformerNode = _find_deformer(deformer, 'zMappedWrapDeformer')
    if deformerNode is None:
        print 'Couldn\'t find a zMappedWrapDeformer deformer on %s.' % deformer
        return
    deformer = deformerNode
   
    # Find the input shape for the deformer.  We need it to create the vertex mapping.
    inputShape = _findDeformerInput(deformer)
    transforms = cmds.listRelatives(inputShape, p=True, path=True, typ='transform')

    # Read the vertices for the input mesh and the new target.
    targetPositions = cmds.xform('%s.vtx[*]' % targetShape, q=True, t=True, ws=True)
    targetPositions = [(x, y, z) for x, y, z in zip(targetPositions[0::3], targetPositions[1::3], targetPositions[2::3])]

    sourcePositions = cmds.xform('%s.vtx[*]' % inputShape, q=True, t=True, ws=True)
    sourcePositions = [(x, y, z) for x, y, z in zip(sourcePositions[0::3], sourcePositions[1::3], sourcePositions[2::3])]
    # print targetPositions
    # print sourcePositions
    
    def findClosestPoint(point):
        closestIndex = -1
        closestDistance = 99999999
        for idx, value in enumerate(sourcePositions):
            distance = math.pow(value[0] - point[0], 2) + math.pow(value[1] - point[1], 2) + math.pow(value[2] - point[2], 2)
#            print value, point, distance
            if distance < closestDistance:
                closestDistance = distance
                closestIndex = idx
        return closestIndex

    # Match vertices in targetPositions to vertices in sourcePositions.
    # XXX: optimize this
    indexMapping = []
    for idx, point in enumerate(targetPositions):
        closestIndex = findClosestPoint(point)
#        print 'closest to', idx, 'is', closestIndex
        indexMapping.append(closestIndex)
    
    deformerIdx = _getNextAvailableIndex(deformer)
    cmds.connectAttr('%s.worldMesh[0]' % (targetShape), '%s.inputTarget[%i].inputGeomTarget' % (deformer, deformerIdx), f=True)
    for idx, value in enumerate(indexMapping):
        cmds.setAttr('%s.inputTarget[%i].vertexIndex[%i]' % (deformer, deformerIdx, idx), value)
    
    ourVertices = set(indexMapping)

    # Check for overlapping vertex influences.
    for idx in cmds.getAttr('%s.inputTarget' % deformer, mi=True):
        if idx == deformerIdx:
            continue

        # Ignore this index if there's no geometry attached.
        connections = cmds.listConnections('%s.inputTarget[%i].inputGeomTarget' % (deformer, idx)) or []
        if not connections:
            continue

        vertices = set(cmds.getAttr('%s.inputTarget[%i].vertexIndex[*]' % (deformer, idx)) or [])
        overlappingVertices = ourVertices & vertices
        if overlappingVertices:
            OpenMaya.MGlobal.displayWarning('New target %s shares %i vertices with existing target %s' % (targetShape, len(overlappingVertices), connections[0]))

