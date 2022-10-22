import pathlib
import random
import subprocess
import tempfile
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


class SelectionGuard():
    """Ensure the same objects are selected at the end."""
    def __init__(self, clear: bool = False):
        self.clear = clear

    def __enter__(self, clear=False):
        self.selected = bpy.context.selected_objects
        if self.clear:
            bpy.ops.object.select_all(action='DESELECT')
        return self

    def __exit__(self, *args, **kwargs):
        bpy.ops.object.select_all(action='DESELECT')
        for obj in self.selected:
            obj.select_set(True)


class ConvexDecompositionBaseOperator(bpy.types.Operator):
    """Base class with common utility methods"""

    bl_idname = 'opr.convex_decomposition_base'
    bl_label = 'Convex Decomposition Base Class'

    def get_selected_object(self) -> Tuple[bpy_types.Object, bool]:
        # User must be in OBJECT mode.
        if bpy.context.mode != 'OBJECT':
            self.report({'ERROR'}, "Must be in OBJECT mode")
            return None, True

        # User must have exactly one object selected.
        selected = bpy.context.selected_objects
        if len(selected) != 1:
            self.report({'ERROR'}, "Must have exactly one object selected")
            return None, True

        return selected[0], False

    def remove_stale_hulls(self, root_obj: bpy_types.Object) -> None:
        with SelectionGuard(clear=True):
            for obj in bpy.data.objects:
                if obj.name.startswith(f"UCX_{root_obj.name}_"):
                    obj.select_set(True)
            bpy.ops.object.delete()

    def rename_hulls(self, hull_prefix: str, obj_name: str) -> List[bpy_types.Object]:
        objs = [_ for _ in bpy.data.objects if _.name.startswith(hull_prefix)]
        for i, obj in enumerate(objs):
            name = f"UCX_{obj_name}_{i}"
            obj.name = name
        return objs


class ConvexDecompositionClearOperator(ConvexDecompositionBaseOperator):
    """Clear all collision shapes for selected object."""

    bl_idname = 'opr.convex_decomposition_clear'
    bl_label = 'Clear Collision Shapes For Selected Object'

    def execute(self, context):
        # User must have exactly one object selected in OBJECT mode.
        root_obj, err = self.get_selected_object()
        if err:
            return {'FINISHED'}

        self.remove_stale_hulls(root_obj)

        self.report({'INFO'}, f"Removed all collision shapes for <{root_obj.name}>")
        return {'FINISHED'}


class ConvexDecompositionUnrealExportOperator(ConvexDecompositionBaseOperator):
    """Clear all collision shapes for selected object."""

    bl_idname = 'opr.convex_decomposition_unreal_export'
    bl_label = 'Export object with Unreal Engine compatible collision meshes as FBX'

    def unreal_export(self, obj: bpy_types.Object) -> None:
        root_path = Path(bpy.path.abspath("//"))
        fname = root_path / f"{obj.name}.fbx"

        # Select all the children of this object.
        with SelectionGuard():
            for child in obj.children:
                if child.name.startswith("UCX_"):
                    child.select_set(True)

            bpy.ops.export_scene.fbx(
                filepath=str(fname),
                check_existing=True,
                use_selection=True,
                mesh_smooth_type="FACE",
                axis_forward='-Z',
                axis_up='Y',
            )
        self.report({'INFO'}, f"Exported object to <{fname}>")

    def execute(self, context):
        # User must have exactly one object selected in OBJECT mode.
        root_obj, err = self.get_selected_object()
        if err:
            return {'FINISHED'}

        self.unreal_export(root_obj)
        return {'FINISHED'}


class ConvexDecompositionRunOperator(ConvexDecompositionBaseOperator):
    """Use VHACD or CoACD to create a convex decomposition of objects."""
    bl_idname = 'opr.convex_decomposition_run'
    bl_label = 'Convex Decomposition Base Class'

    def upsert_collection(self, collection_name: str) -> bpy_types.Collection:
        """ Upsert a dedicated outliner collection for the convex hulls."""
        try:
            collection = bpy.data.collections[collection_name]
        except KeyError:
            collection = bpy.data.collections.new(collection_name)
            bpy.context.scene.collection.children.link(collection)
        return collection

    def randomise_colour(self, obj: bpy_types.Object) -> None:
        red, green, blue = [random.random() for _ in range(3)]
        alpha = 1.0
        material = bpy.data.materials.new("random material")
        material.diffuse_color = (red, green, blue, alpha)
        obj.data.materials.clear()
        obj.data.materials.append(material)

    def export_mesh_for_solver(self, obj: bpy_types.Object, path: Path) -> Path:
        with SelectionGuard(clear=True):
            obj.select_set(True)

            fname = path / "src.obj"
            bpy.ops.export_scene.obj(
                filepath=str(fname),
                check_existing=False,
                use_selection=True,
                use_materials=False,
            )
        return fname

    def run_vhacd(self, obj_file: Path):
        # Call VHACD to do the convex decomposition.
        args = [
            "vhacd", str(obj_file),
        ]
        subprocess.run(args, cwd=obj_file.parent)

        fout = obj_file.parent / "decomp.obj"
        return fout

    def run_coacd(self, obj_file: Path) -> Path:
        # Call CoACD to do the convex decomposition.
        result_file = obj_file.parent / "hulls.obj"
        args = [
            "coacd", "-i", str(obj_file),
            "-o", str(result_file),
            "-np", "-mi", "400", "-md", "5",
            "-mn", "40", "-t", "0.05",
        ]
        subprocess.run(args, cwd=obj_file.parent)
        return result_file

    def import_solver_results(self, fname: Path, hull_prefix: str):
        # Replace all object names in the OBJ file that CoACD produced.
        data = ""
        lines = fname.read_text().splitlines()
        for i, line in enumerate(lines):
            if line.startswith("o "):
                data += f"o {hull_prefix}{i}\n"
            else:
                data += line + "\n"
        fname.write_text(data)

        # Import the hulls back into Blender.
        with SelectionGuard():
            bpy.ops.import_scene.obj(
                filepath=str(fname),
                filter_glob='*.obj',
            )

    def execute(self, context):
        # Convenience.
        props = context.scene.ConvDecompProperties

        # User must have exactly one object selected in OBJECT mode.
        root_obj, err = self.get_selected_object()
        if err:
            return {'FINISHED'}
        self.report({'INFO'}, f"Computing collision meshes for <{root_obj.name}>")

        self.remove_stale_hulls(root_obj)

        # Save the selected root object as a temporary .obj file and use at
        # as input for the solver.
        tmp_path = Path(tempfile.mkdtemp(prefix="devcomp-"))
        print(f"Created temporary directory for solvers: {tmp_path}")

        obj_path = self.export_mesh_for_solver(root_obj, tmp_path)
        hull_path = self.run_vhacd(obj_path)
        self.import_solver_results(hull_path, props.tmp_hull_prefix)
        del obj_path, hull_path

        # Clean up the object names in Blender after the import.
        hull_objs = self.rename_hulls(props.tmp_hull_prefix, root_obj.name)

        # Parent the hulls to the root object, randomise their colours and place
        # them into a dedicated Blender collection.
        hull_collection = self.upsert_collection(props.hull_collection_name)
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
        elif props.solver == "CoACD":
            prefix = "c_"
        else:
            self.report({'ERROR'}, "Unknown Solver <{props.solver}>")
            return

        # Display "Run" button.
        layout.row().operator('opr.convex_decomposition_run', text="Run")

        # Display Clear and Export buttons.
        row = layout.row()
        row.operator('opr.convex_decomposition_clear', text="Clear")
        row.operator('opr.convex_decomposition_unreal_export', text="Export")

        # Shared parameters.
        layout.row().prop(props, "both")

        # Solver Specific parameters.
        solver_specific = [_ for _ in props.__annotations__ if _.startswith(prefix)]
        for name in solver_specific:
            layout.row().prop(props, name)


class ConvexDecompositionProperties(bpy.types.PropertyGroup):
    v_param: bpy.props.FloatProperty(  # type: ignore
        name="v_Param",
        description="VHACD Parameter",
        default=1.0,
    )
    c_param: bpy.props.FloatProperty(  # type: ignore
        name="c_Param",
        description="CoACD Parameter",
        default=2.0,
    )
    both: bpy.props.FloatProperty(  # type: ignore
        name="Shared parameter",
        description="Shared Parameter",
        default=3.0,
    )
    tmp_hull_prefix: bpy.props.StringProperty(  # type: ignore
        name="Hull Prefix",
        description="Name prefix for the temporary hull names created by the solvers.",
        default="_tmphull_",
    )
    hull_collection_name: bpy.props.StringProperty(  # type: ignore
        name="Hull Collection",
        description="The collection to hold all the convex hulls.",
        default="convex hulls",
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


CLASSES = [
    ConvexDecompositionPanel,
    ConvexDecompositionProperties,
    ConvexDecompositionRunOperator,
    ConvexDecompositionClearOperator,
    ConvexDecompositionUnrealExportOperator,
]

def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.ConvDecompProperties = bpy.props.PointerProperty(type=ConvexDecompositionProperties)

def unregister():
    for cls in CLASSES:
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.ConvDecompProperties


register()