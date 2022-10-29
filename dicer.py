"""Take the select object and dice it into cubes.

The idea was to use this a pre-processing step for a convex decomposition since
it produces smaller volumes that are already somewhat (or fully) convex due to
the cutting planes.

"""
from typing import List

import bpy  # type: ignore
import bpy_types  # type: ignore
import numpy as np  # type: ignore


def remove_obj(obj: bpy_types.Object) -> None:
    """Delete `obj` from the scene."""
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.ops.object.delete()


def duplicate_object(src_obj: bpy_types.Object) -> bpy_types.Object:
    """Duplicate `src_obj` and return the duplicated object."""
    bpy.ops.object.select_all(action="DESELECT")
    src_obj.select_set(True)

    bpy.ops.object.duplicate()
    assert len(bpy.context.selected_objects) == 1

    dst_obj = bpy.context.selected_objects[0]

    # IMPORTANT: Make the selected object "active". I do not know what this
    # does exactly yet but strange things will happen without it.
    bpy.context.view_layer.objects.active = dst_obj

    return dst_obj


def slice_obj_with_planes(src_obj: bpy_types.Object,
              plane: str,
              offset: np.ndarray) -> List[bpy_types.Object]:
    """Slice `src_obj` and return the sliced objects.

    The `plane` argument specifies the axis aligned plane and must be one of
    {"xy", "xz" or "yz"}.

    The `offset` argument  determines the location of the planes. For instance,
    `slice_obj(obj, "xy", offset=[-1, 0, 1]` will return two slices. The first slice
    will be the volume between two XY planes located at z=[-1, 0]. The second
    one will be the same except the `z` offsets will be [0, 1].

    """
    # Convert string input to plane normals.
    plane_normals = dict(
        xy=np.array([0, 0, 1]),
        xz=np.array([0, 1, 0]),
        yz=np.array([1, 0, 0]),
    )
    plane_normal = plane_normals[plane.lower()]

    # Ensure we are in object mode.
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    # Two create one slice we need to bisect the object twice with the same
    # plane normal, just at different offset. Here we loop over all those plane
    # pairs to create the corresponding slice.
    slice_objs = []
    for z0, z1 in zip(offset[:-1], offset[1:]):
        # Duplicate the object and switch to EDIT mode because Blender's bisect
        # operator does not work in OBJECT mode.
        obj = duplicate_object(src_obj)
        bpy.ops.object.mode_set(mode="EDIT")

        # Define the bisection planes.
        point_on_top_plane = plane_normal * z1
        point_on_bottom_plane = plane_normal * z0

        # Chop off the top part.
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.bisect(
            plane_no=plane_normal,
            plane_co=point_on_top_plane,
            clear_outer=True, clear_inner=False,
            use_fill=True,
        )

        # Chop off the bottom part.
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.bisect(
            plane_no=plane_normal,
            plane_co=point_on_bottom_plane,
            clear_outer=False, clear_inner=True,
            use_fill=True,
        )

        # Switch back to OBJECT mode because we need to apply the correct
        # transforms to ensure each slice is centred around its local origin an
        # the wold position determines its position in the scene.
        bpy.ops.object.mode_set(mode="OBJECT")

        # Apply the transforms. First we need to backup the current location
        # and void it.
        orig_loc = obj.location.copy()
        obj.location = (0, 0, 0)

        # Pick point in the middle of the two planes, ie the location of the slice.
        slice_loc = plane_normal * ((z0 + z1) / 2)

        # Offset the object by the slice offset, apply the transform and then
        # re-add the slice offset.
        obj.location = -slice_loc
        bpy.ops.object.transform_apply()
        obj.location = np.array(orig_loc) + slice_loc

        # Add the object to the output list.
        slice_objs.append(obj)

    return slice_objs


def slice_obj(src_obj: bpy_types.Object, ofs: List[float]):
    """Chop `src_obj` along an equilateral cubic grid and return the slices."""
    # Slice the source object along several XY planes.
    slice_xy = slice_obj_with_planes(src_obj, "xy", ofs)

    # Slice the XY slices along several XZ planes.
    slice_xz = []
    for obj in slice_xy:
        slice_xz += slice_obj_with_planes(obj, "xz", ofs)
        remove_obj(obj)

    # Slice the XZ slices along several YZ planes.
    slice_yz = []
    for obj in slice_xz:
        slice_yz += slice_obj_with_planes(obj, "yz", ofs)
        remove_obj(obj)

    # Rename the slices.
    for i, obj in enumerate(slice_yz):
        obj.name = f"slice-{i}"

    return slice_yz


def create_test_object():
    """Create a dummy object for testing."""
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()

    bpy.ops.mesh.primitive_ico_sphere_add(
        subdivisions=2, radius=1.0, calc_uvs=True, enter_editmode=False,
        align='WORLD',
        location=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0)
    )

def explode_obj(objs: List[bpy_types.Object], factor: float):
    """Helper function: explode the slices."""
    for obj in objs:
        obj.location *= factor


def main():
    """Create a dummy object and slice it."""
    create_test_object()

    # Exactly one object must be selected right now.
    assert len(bpy.context.selected_objects) == 1
    src_obj = bpy.context.selected_objects[0]

    # Create 4 slices along each axis. This will produce a total of 4x4x4=64
    # slices for the given object.
    ofs = np.linspace(-0.8, 0.8, 5)

    # Create the slices.
    slices = slice_obj(src_obj, ofs)

    # Explode the slices for visual inspection.
    explode_obj(slices, 1.5)

    # Re-select the original object.
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    src_obj.select_set(True)

main()
