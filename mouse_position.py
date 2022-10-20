import bpy


class SimpleMouseOperator(bpy.types.Operator):
    """ This operator shows the mouse location,
        this string is used for the tooltip and API docs
    """
    bl_idname = "wm.mouse_position"
    bl_label = "Invoke Mouse Operator"

    x: bpy.props.IntProperty()
    y: bpy.props.IntProperty()

    def execute(self, context):
        # rather than printing, use the report function,
        # this way the message appears in the header,
        self.report({'INFO'}, "Mouse coords are %d %d" % (self.x, self.y))
        return {'FINISHED'}

    def invoke(self, context, event):
        self.x = event.mouse_x
        self.y = event.mouse_y
        return self.execute(context)


# Only needed if you want to add into a dynamic menu.
def menu_func(self, context):
    self.layout.operator(SimpleMouseOperator.bl_idname, text="Simple Mouse Operator")


# Register and add to the view menu (required to also use F3 search "Simple Mouse Operator" for quick access)
bpy.utils.register_class(SimpleMouseOperator)
bpy.types.VIEW3D_MT_view.append(menu_func)
