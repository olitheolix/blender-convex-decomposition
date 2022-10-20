import pathlib
import random
import subprocess
from pathlib import Path

import bpy


class ConvexDecompositionVHACD(bpy.types.Operator):
    """ This operator produces used VHACD to produce Unreal compliant collision
        shapes for it.
    """
    bl_idname = "wm.vhacd"
    bl_label = "Convex Decomposition of Selected Object"

    def execute(self, context):
        if bpy.context.object.mode == 'EDIT':
            self.report({'ERROR'}, "Must be in Object mode to use Convex Decomposition")
            return {'FINISHED'}

        selected = bpy.context.selected_objects
        if len(selected) != 1:
            self.report({'INFO'}, "Must have exactly one object selected")
            return
        orig_name = selected[0].name
        self.report({'INFO'}, f"Computing Collision Meshes for <{orig_name}>")

        fpath = Path("/tmp/foo")
        pathlib.Path.mkdir(fpath, exist_ok=True)
        fname = fpath / "src.obj"
        bpy.ops.export_scene.obj(filepath=str(fname), check_existing=False,
                                 use_selection=True, use_materials=False)
        # Call VHACD to do the convex decomposition.
        subprocess.run(["vhacd", str(fname), "-o", "obj"])

        fname.unlink()
        pattern = str(fname.stem) + "*.obj"
        out_files = list(fpath.glob(pattern))
        self.report({"INFO"}, f"Produced {len(out_files)} Collision Meshes")

        # Deselect all objects.
        bpy.ops.object.select_all(action='DESELECT')

        # Select all VHACD collision objects from a previous run if there were any.
        for obj in bpy.data.objects:
            if obj.name.startswith(f"UCX_{orig_name}_"):
                obj.select_set(True)
        bpy.ops.object.delete()

        try:
            vhacd_collection = bpy.data.collections["vhacd"]
        except KeyError:
            vhacd_collection = bpy.data.collections.new("vhacd")
            bpy.context.scene.collection.children.link(vhacd_collection)

        for fname in out_files:
            # Import the new object. Blender will automatically select it.
            bpy.ops.import_scene.obj(filepath=str(fname), filter_glob='*.obj')

            # Sanity check: Blender must have selected the just imported object.
            selected = bpy.context.selected_objects
            assert len(selected) == 1
            obj = selected[0]

            # Extract the numerical suffix, ie /tmp/src012.obj -> 012
            stem_name = str(fname.stem)  # eg /tmp/src012.obj -> src012
            suffix = stem_name.partition("src")[2]  # src012 -> 012

            # Rename the object to match Unreal's FBX convention for collision shapes.
            obj.name = f"UCX_{orig_name}_{suffix}"

            # Unlink the current object from all its collections.
            for coll in obj.users_collection:
                coll.objects.unlink(obj)

            red, green, blue = random.random(), random.random(), random.random()
            alpha = 0.5
            material = bpy.data.materials.new("vhacd random material")
            material.diffuse_color = (red, green, blue, alpha)
            obj.data.materials.clear()
            obj.data.materials.append(material)

            # Link the object to our dedicated VHACD collection.
            vhacd_collection.objects.link(obj)

        # Re-select the original object again for a consistent user experience.
        bpy.ops.object.select_all(action='DESELECT')
        bpy.data.objects[orig_name].select_set(True)

        return {'FINISHED'}

    def invoke(self, context, event):
        self.x = event.mouse_x
        self.y = event.mouse_y
        return self.execute(context)

# Only needed if you want to add into a dynamic menu.
def menu_func(self, context):
    self.layout.operator(ConvexDecompositionVHACD.bl_idname, text="Convex Decomposition for Unreal Engine")

# Register and add to the view menu (required to also use F3 search "Simple Mouse Operator" for quick access)
bpy.utils.register_class(ConvexDecompositionVHACD)
bpy.types.VIEW3D_MT_view.append(menu_func)

