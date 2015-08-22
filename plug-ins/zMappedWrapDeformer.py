import maya.OpenMayaMPx as OpenMayaMPx
import maya.OpenMaya as OpenMaya
import pymel.core
import math, traceback, time

if OpenMaya.MGlobal.apiVersion() < 201600:
    MPxGeometryFilter_outputGeom = OpenMayaMPx.cvar.MPxDeformerNode_outputGeom
    MPxGeometryFilter_input = OpenMayaMPx.cvar.MPxDeformerNode_input
    MPxGeometryFilter_inputGeom = OpenMayaMPx.cvar.MPxDeformerNode_inputGeom
    MPxGeometryFilter_groupId = OpenMayaMPx.cvar.MPxDeformerNode_groupId
else:
    MPxGeometryFilter_outputGeom = outputGeom = OpenMayaMPx.cvar.MPxGeometryFilter_outputGeom
    MPxGeometryFilter_input = OpenMayaMPx.cvar.MPxGeometryFilter_input
    MPxGeometryFilter_inputGeom = OpenMayaMPx.cvar.MPxGeometryFilter_inputGeom
    MPxGeometryFilter_groupId = OpenMayaMPx.cvar.MPxGeometryFilter_groupId

def array_current_index(array):
    """
    Return the current index (elementIndex()) of a MArrayDataHandle, or -1 if the
    current index isn't valid, probably because the array is empty.
    """
    try:
        return array.elementIndex()
    except RuntimeError as e:
        # If the array is empty, elementIndex raises an error.
        return -1

def iterate_array_handle(array):
    """
    Mostly fix MArrayDataHandle array iteration.
    """
    while True:
        # Call elementIndex() to see if there are any values at all.  It'll throw RuntimeError
        # if there aren't.
        try:
            array.elementIndex()
        except RuntimeError as e:
            # We've advanced beyond the end of the array.
            break

        yield array.inputValue()

        try:
            array.next()
        except RuntimeError as e:
            break

class zMappedWrapDeformer(OpenMayaMPx.MPxDeformerNode):
    pluginNodeId = OpenMaya.MTypeId(0x124741)

    def __init__(self):
        super(zMappedWrapDeformer, self).__init__()
        self.cached_inversion_matrices = None

    def deform(self, dataBlock, geomIter, objectToWorldSpaceMatrix, multiIndex):
        # If the envelope for the deformer itself is very small, stop.
        envelope = dataBlock.inputValue(self.envelope).asFloat()
        if envelope < 0.001:
            return

        # Read the input mesh.
        #
        # XXX: We should be using world space here, but we've been given an iterator
        # with no DAG path.  (The caller knows our world space, so it has a DAG path,
        # so this is strange.)  How can we get world space without manually multiplying
        # by matrix?  This would avoid needing to do a bunch of matrix multiplications
        # in the inner loop below.
        points = OpenMaya.MPointArray()
        geomIter.allPositions(points, OpenMaya.MSpace.kObject)
        worldToObjectSpaceMatrix = objectToWorldSpaceMatrix.inverse()

        targetEnvelopes = dataBlock.inputArrayValue(zMappedWrapDeformer.targetEnvelopeAttr)

        # Be careful to not call inputArrayValue on inputsAttr.  That'll evaluate all input
        # meshes, even ones that are currently disabled.
        inputsPlug = OpenMaya.MPlug(self.thisMObject(), zMappedWrapDeformer.inputsAttr)
        for inputIdx in xrange(inputsPlug.numElements()):
            try:
                inputPlug = inputsPlug.connectionByPhysicalIndex(inputIdx)
            except RuntimeError:
                # There's nothing connected to this input.
                continue

            # Read this target's envelope.
            try:
                targetEnvelopes.jumpToElement(inputPlug.logicalIndex())
                targetEnvelope = targetEnvelopes.inputValue().asFloat()
            except RuntimeError:
                # There's no element at this index, so use the default of 1.
                targetEnvelope = 1

            # If the envelope for this mesh is very small, skip it without reading the input.
            if targetEnvelope < 0.001:
                continue
            
            # Get the mapping from target vertex indices to the input.
            vertexIndices = inputPlug.child(self.vertexIndexAttr)
            if vertexIndices.evaluateNumElements() == 0:
                continue

            # Get the target geometry.
            inputGeomTarget = inputPlug.child(self.inputGeomTargetAttr)
            targetMesh = OpenMaya.MFnMesh(inputGeomTarget.asMObject())
            targetPoints = OpenMaya.MFloatPointArray()
            targetMesh.getPoints(targetPoints, OpenMaya.MSpace.kWorld)

            # Combine the envelope for the deformer itself with the envelope for this target.
            targetEnvelope *= targetEnvelope * envelope
            oneMinusEnvelope = 1-targetEnvelope

            # Take a faster code path if the envelope is 1.
            targetEnvelopeIsOne = abs(1 - targetEnvelope) < 0.001

            for index in xrange(vertexIndices.evaluateNumElements()):
                vertexIndex = vertexIndices.elementByPhysicalIndex(index)

                # The index in the target shape:
                targetIndex = vertexIndex.logicalIndex()
                if targetIndex >= targetPoints.length():
                    break

                # The index in the input shape.
                inputIndex = vertexIndex.asInt()

                # Index -1 means that we couldn't find any matching vertex for this index, and
                # it should be skipped.
                if inputIndex >= points.length() or inputIndex == -1:
                    continue

                targetVertex = targetPoints[targetIndex]
                if targetEnvelopeIsOne:
                    # If envelope == 1, we don't need to look at the input vertex at all.  We're
                    # just replacing the vertex position entirely.
                    result = targetVertex
                else:
                    # Get the input position in world space, blend it with the world space position
                    # of the target vertex, then convert it back to object space.
                    inputVertex = points[inputIndex] * objectToWorldSpaceMatrix
                    result = OpenMaya.MVector(targetVertex*targetEnvelope) + OpenMaya.MVector(inputVertex*oneMinusEnvelope)

                result = OpenMaya.MPoint(result) * worldToObjectSpaceMatrix
                points.set(inputIndex, result.x, result.y, result.z)

        # Save the deformed mesh.
        geomIter.setAllPositions(points, OpenMaya.MSpace.kObject)

def creator():
    return OpenMayaMPx.asMPxPtr(zMappedWrapDeformer())

def initialize():
    mAttr = OpenMaya.MFnMatrixAttribute()
    tAttr = OpenMaya.MFnTypedAttribute()
    nAttr = OpenMaya.MFnNumericAttribute()
    cmpAttr = OpenMaya.MFnCompoundAttribute()

    # A map of target vertices.  Vertex n in inputGeomTarget is written to vertexIndex[n] in the
    # input geometry.
    zMappedWrapDeformer.vertexIndexAttr = nAttr.create('vertexIndex', 'vi', OpenMaya.MFnNumericData.kInt)
    nAttr.setArray(True)
    nAttr.setHidden(True)
    nAttr.setUsesArrayDataBuilder(True)
    zMappedWrapDeformer.addAttribute(zMappedWrapDeformer.vertexIndexAttr)
    zMappedWrapDeformer.attributeAffects(zMappedWrapDeformer.vertexIndexAttr, MPxGeometryFilter_outputGeom)

    # The target geometry.
    zMappedWrapDeformer.inputGeomTargetAttr = tAttr.create('inputGeomTarget', 'igt', OpenMaya.MFnData.kMesh)
    tAttr.setDisconnectBehavior(tAttr.kReset)
    tAttr.setHidden(True)
    zMappedWrapDeformer.addAttribute(zMappedWrapDeformer.inputGeomTargetAttr)
    zMappedWrapDeformer.attributeAffects(zMappedWrapDeformer.inputGeomTargetAttr, MPxGeometryFilter_outputGeom)

    # A per-target envelope.  This is combined with the deformer's main envelope.
    zMappedWrapDeformer.targetEnvelopeAttr = nAttr.create('weight', 'wt', OpenMaya.MFnNumericData.kFloat, 1)
    nAttr.setChannelBox(True)
    nAttr.setArray(True)
    nAttr.setSoftMin(0)
    nAttr.setSoftMax(1)
    nAttr.setKeyable(True)
    zMappedWrapDeformer.addAttribute(zMappedWrapDeformer.targetEnvelopeAttr)
    zMappedWrapDeformer.attributeAffects(zMappedWrapDeformer.targetEnvelopeAttr, MPxGeometryFilter_outputGeom)

    # The main list of input targets.
    zMappedWrapDeformer.inputsAttr = cmpAttr.create('inputTarget', 'it')
    cmpAttr.setArray(True)
    cmpAttr.addChild(zMappedWrapDeformer.vertexIndexAttr)
    cmpAttr.addChild(zMappedWrapDeformer.inputGeomTargetAttr)
    zMappedWrapDeformer.addAttribute(zMappedWrapDeformer.inputsAttr)
    zMappedWrapDeformer.attributeAffects(zMappedWrapDeformer.inputsAttr, MPxGeometryFilter_outputGeom)

def initializePlugin(mobject):
    plugin = OpenMayaMPx.MFnPlugin(mobject)
    plugin.registerNode('zMappedWrapDeformer', zMappedWrapDeformer.pluginNodeId, creator,
            initialize, OpenMayaMPx.MPxNode.kDeformerNode)

def uninitializePlugin(mobject):
    plugin = OpenMayaMPx.MFnPlugin(mobject)
    plugin.deregisterNode(zMappedWrapDeformer.pluginNodeId)

