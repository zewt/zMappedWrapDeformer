This Maya plug-in allows wrapping portions of a mesh to another mesh.  This
works like the wrap deformer, but the vertex associations are made when a
target is added, rather than on the fly.

This can be used to separate portions of a rig.  For example, a character's
face can be separated and rigged on its own, and then wrapped to the main
character model.  nCloth and other dynamics systems can also be isolated
for portions of a rig.

Installation
------------

Install by copying zWrappedMapDeformer.mod into Maya's modules
directory and setting the correct path, and adding this to your userSetup.mel:

```
source "zMappedWrapDeformerMenu.mel";
```

A "Mapped Wrap" menu will be added to the Deform menu in the Rigging menu set.

Usage
-----

Select Mapped Wrap > Create to add a mapped wrap deformer to a mesh.

Select a mesh and a target, then select Mapped Wrap > Add Target to add a
target to the deformer.  The meshes don't need to have the same topology,
but the vertices in the target should overlap vertices in the deformed mesh.
A vertex mapping will be saved with the deformer.



Notes
-----

This is meant to be used with non-overlapping targets.  For example, you
can have a target that is just the character's head, and another target
for just the character's hands.  If targets have overlapping vertices,
and more than one overlapping target is enabled at a time, note that the
order of inputs matters: one target will be blended in, then the next, and
so on.  If they're all set to an envelope of 1, the last target is the one
that will be used.  This matters if you're trying to transition from one
to another.

Known issues
------------

Deleting a target connection should reset the input, but instead the old
mesh connection keeps being used.  disconnectBehavior is set to kReset, so
this shouldn't be happening.

Matching vertices is a brute force search, and needs to be optimized for
dense meshes.

Normals are currently not copied.  I'll do this after I've tested this with
just vertices first.

