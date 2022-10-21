import pathlib
import random
import subprocess
from pathlib import Path
from typing import List, Tuple

import bpy  # type: ignore
import bpy_types  # type: ignore

bl_info = {
    'name': 'Unreal Blender',
    'blender': (3, 4, 0),
    'category': 'Object',
    'version': (0, 1, 0),
    'author': 'Oliver Nagy',
    'description': 'Create collision shapes and export them to Unreal Engine',
    'warning': 'WIP',
}


class ConvexDecompositionOperator(bpy.types.Operator):
    """Use VHACD or CoACD to create convex decompositions of objects.
    """

    bl_idname = 'opr.convex_decomp'
    bl_label = 'Convex Decomposition'

    def make_collection(self, collection_name: str) -> bpy_types.Collection:
        """ Upsert a dedicated outliner collection for the convex hulls."""
        try:
            collection = bpy.data.collections[collection_name]
        except KeyError:
            collection = bpy.data.collections.new(collection_name)
            bpy.context.scene.collection.children.link(collection)
        return collection

    def export_object(self) -> Path:
        fpath = Path("/tmp/foo")
        pathlib.Path.mkdir(fpath, exist_ok=True)
        fname = fpath / "src.obj"
        bpy.ops.export_scene.obj(filepath=str(fname), check_existing=False,
                                 use_selection=True, use_materials=False)
        return fname

    def remove_stale_hulls(self, name: str) -> None:
        bpy.ops.object.select_all(action='DESELECT')
        for obj in bpy.data.objects:
            if obj.name.startswith(f"UCX_{name}_"):
                obj.select_set(True)
        bpy.ops.object.delete()

    def randomise_colour(self, obj: bpy_types.Object) -> None:
        red, green, blue = [random.random() for _ in range(3)]
        alpha = 1.0
        material = bpy.data.materials.new("random material")
        material.diffuse_color = (red, green, blue, alpha)
        obj.data.materials.clear()
        obj.data.materials.append(material)

    def merge_obj_files(self, prefix: str, out_files: List[Path]) -> Path:
        data = ""
        vert_ofs = 0

        # Concatenate all OBJ files and assign each mesh a unique name.
        for i, fname in enumerate(out_files):
            data += f"o {prefix}{i}\n"

            vert_cnt = 0
            for line in fname.read_text().splitlines():
                if line.startswith("v "):
                    vert_cnt += 1
                    data += line + "\n"
                elif line.startswith("f "):
                    el = line.split()
                    vert_idx = [int(_) for _ in el[1:]]
                    vert_idx = [str(_ + vert_ofs) for _ in vert_idx]
                    data += "f " + str.join(" ", vert_idx) + "\n"
                else:
                    self.report({'ERROR'}, f"Unknown OBJ line entry <{line}>")
                    assert False
            vert_ofs += vert_cnt

        out = Path("/tmp/foo/merged.obj")
        out.write_text(data)
        return out

    def rename_hulls(self, hull_prefix: str, obj_name: str) -> List[bpy_types.Object]:
        objs = [_ for _ in bpy.data.objects if _.name.startswith(hull_prefix)]
        for i, obj in enumerate(objs):
            name = f"UCX_{obj_name}_{i}"
            obj.name = name
        return objs

    def run_vhacd(self, obj_file_path: Path, hull_prefix: str):
        # Call VHACD to do the convex decomposition.
        subprocess.run(["vhacd", str(obj_file_path), "-o", "obj"])

        # Delete the original object from the temporary location and fetch the
        # list of all created collision shapes.
        obj_file_path.unlink()
        pattern = str(obj_file_path.stem) + "*.obj"
        out_files = list(obj_file_path.parent.glob(pattern))
        self.report({"INFO"}, f"Produced {len(out_files)} Convex Hulls")

        merged_obj_file = self.merge_obj_files(hull_prefix, out_files)
        bpy.ops.import_scene.obj(filepath=str(merged_obj_file), filter_glob='*.obj')
        del merged_obj_file

    def get_selected_object(self) -> Tuple[bpy_types.Object, bool]:
        # User must be in OBJECT mode.
        if bpy.context.object.mode != 'OBJECT':
            self.report({'ERROR'}, "Must be in OBJECT mode")
            return None, True

        # User must have exactly one object selected.
        selected = bpy.context.selected_objects
        if len(selected) != 1:
            self.report({'ERROR'}, "Must have exactly one object selected")
            return None, True

        return selected[0], False

    def execute(self, context):
        props = context.scene.ConvDecompProperties
        self.report({'INFO'}, f"Using {props.solver}")

        collection_name = "convex hulls"
        tmp_obj_prefix = "_tmphull_"

        root_obj, err = self.get_selected_object()
        if err:
            return {'FINISHED'}

        self.report({'INFO'}, f"Computing Collision Meshes for <{root_obj.name}>")
        self.remove_stale_hulls(root_obj.name)

        # Save the selected root object as a temporary .obj file.
        tmp_obj_path = self.export_object()

        # Run the convex decomposition.
        self.run_vhacd(tmp_obj_path, tmp_obj_prefix)
        del tmp_obj_path

        # Clean up the object names after the import.
        hull_objs = self.rename_hulls(tmp_obj_prefix, root_obj.name)

        # Parent the hulls to the root object, randomise their colour and place
        # them into a dedicated collection.
        hull_collection = self.make_collection(collection_name)
        for obj in hull_objs:
            # Unlink the current object from all its collections.
            for coll in obj.users_collection:
                coll.objects.unlink(obj)

            # Link the object to our dedicated collection.
            hull_collection.objects.link(obj)

            # Assign a random colour to the hull.
            self.randomise_colour(obj)

            # Parent the hull to the root object without changing the relative transform.
            obj.parent = root_obj
            obj.matrix_parent_inverse = root_obj.matrix_world.inverted()

        # Re-select the root object again for a consistent user experience.
        bpy.ops.object.select_all(action='DESELECT')
        root_obj.select_set(True)

        return {'FINISHED'}


class ConvexDecompositionPanel(bpy.types.Panel):
    bl_idname = 'VIEW3D_PT_ConvDec'
    bl_label = 'Convex Decomposition'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "ConvDecomp"

    def draw(self, context):
        # Convenience.
        props = context.scene.ConvDecompProperties
        layout = self.layout

        layout.prop(props, 'solver')
        if props.solver == "VHACD":
            prefix = "v_"
            solver = "opr.convex_decomp"
        else:
            prefix = "c_"
            solver = "opr.convex_decomp"

        layout.row().operator(solver, text="Run")
        layout.row().prop(props, "both")
        solver_specific = [_ for _ in props.__annotations__ if _.startswith(prefix)]
        for name in solver_specific:
            layout.row().prop(props, name)


class ConvexDecompositionProperties(bpy.types.PropertyGroup):
    v_param: bpy.props.FloatProperty(  # type: ignore
        name="v_Param",
        description="VHACD Parameter"
    )
    c_param: bpy.props.FloatProperty(  # type: ignore
        name="c_Param",
        description="CoACD Parameter"
    )
    both: bpy.props.FloatProperty(  # type: ignore
        name="Shared parameter",
        description="Shared Parameter"
    )
    solver : bpy.props.EnumProperty(                    # type: ignore
        name="Solver",
        description="Select Convex Decomposition Solver",
        items={
            ('VHACD', 'VHACD', 'Use VHACD'),
            ('CoACD', 'CoACD', 'Use CoACD'),
        },
        default='VHACD',
    )


CLASSES = [ConvexDecompositionPanel, ConvexDecompositionOperator, ConvexDecompositionProperties]

def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.ConvDecompProperties = bpy.props.PointerProperty(type=ConvexDecompositionProperties)

def unregister():
    for cls in CLASSES:
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.ConvDecompProperties


register()
