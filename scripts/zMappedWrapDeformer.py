import maya.cmds as cmds
import maya.OpenMaya as OpenMaya
import maya.OpenMayaAnim as OpenMayaAnim
import bisect, math, time

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

def _isTargetForDeformer(deformer, targetShape):
    try:
        connections = cmds.listConnections('%s.inputTarget[*].inputGeomTarget' % deformer, p=True) or []
    except ValueError as e:
        # This throws "no object matches name" if there are no entries at all.
        return False

    fullPath = cmds.ls('%s.worldMesh' % targetShape, l=True)[0]
    for existingConnection in connections:
        existingConnection = cmds.ls(existingConnection, l=True)[0]
        if existingConnection == fullPath:
            return True
    return False

def _findClosestPoint(data, value, tol=0.001):
    """
    Given a list of values sorted by their X coordinate, find the closest point
    within the specified tolerance.

    A more robust approach would be a BSP tree or other 3d structure, but this
    handles most meshes fine.  This will be slow if the input mesh is a 2d object
    along the YZ plane, in which case the X coordinates will all be the same.
    We could detect that case and swap the coordinates to sort on a different
    axis if we needed to.
    """
    # The values are sorted by their X value.  Do a binary search to find a starting
    # point, which will give an X value near the one we're looking for.  bisect does
    # strictly define the index it gives, but we're going to traverse in both directions
    # until we pass the tolerance, so we don't care.
    start_idx = bisect.bisect_left(data, (value[0] - tol, value[1], value[2]))
    end_idx = bisect.bisect_left(data, (value[0] + tol, value[1], value[2]))

    nearest_idx = -1
    nearest_idx_distance = 99999999
    tolerance_squared = pow(tol, 2)
    for idx in xrange(start_idx, end_idx):
        point = data[idx]

        distance_squared = pow(point[0] - value[0], 2) + pow(point[1] - value[1], 2) + pow(point[2] - value[2], 2)
        # print 'point', point, value, distance_squared, pow(distance_squared, 0.5)
        if distance_squared > tolerance_squared:
            continue

        # If this point is closer than the best match we have, update the match.  However,
        # don't stop iterating if it's further, since it may just be further on an axis
        # other than the one we sorted on.
        if nearest_idx == -1 or distance_squared < nearest_idx_distance:
            nearest_idx_distance = distance_squared
            nearest_idx = idx
    return nearest_idx

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
   
    if _isTargetForDeformer(deformer, targetShape):
        OpenMaya.MGlobal.displayWarning('%s is already a target for %s.' % (targetShape, deformer))
        return

    # Find the input shape for the deformer.  We need it to create the vertex mapping.
    inputShape = _findDeformerInput(deformer)
    transforms = cmds.listRelatives(inputShape, p=True, path=True, typ='transform')

    # Read the vertices for the input mesh and the new target.
    targetPositions = cmds.xform('%s.vtx[*]' % targetShape, q=True, t=True, ws=True)
    targetPositions = [(x, y, z) for x, y, z in zip(targetPositions[0::3], targetPositions[1::3], targetPositions[2::3])]

    sourcePositions = cmds.xform('%s.vtx[*]' % inputShape, q=True, t=True, ws=True)
    sourcePositions = [(x, y, z) for x, y, z in zip(sourcePositions[0::3], sourcePositions[1::3], sourcePositions[2::3])]
    
    # Store the index of each point, so we can recover the original index after sorting.
    sourcePositions = [(x, y, z, idx) for idx, (x, y, z) in enumerate(sourcePositions)]

    # Sort the keys by their X coordinate, which _findClosestPoint requires.
    sourcePositions.sort(key=lambda value: value[0])
    # print 'target', targetPositions
    # print 'source', sourcePositions
    
    # Match vertices in targetPositions to vertices in sourcePositions.
    indexMapping = []
    unmatchedVertices = 0
    for idx, point in enumerate(targetPositions):
        closestIndex = _findClosestPoint(sourcePositions, point, tol=tolerance)
        if closestIndex != -1:
            # Pull out the original value, which we stored in the tuple above.
            closestIndex = sourcePositions[closestIndex][3]
        else:
            unmatchedVertices += 1

        indexMapping.append(closestIndex)

    if unmatchedVertices > 0:
        OpenMaya.MGlobal.displayWarning('%i of %i vertices couldn\'t be matched' % (unmatchedVertices, len(targetPositions)))
    else:
        OpenMaya.MGlobal.displayInfo('All %i vertices were matched' % (len(targetPositions)))
    
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

