import bpy


bl_info = {
    "name": "Bake Rigify rig",
    "author": "Felix Schlitter",
    "version": (0, 1),
    "blender": (2, 6, 3),
    "category": "Import-Export"
}


def poll_valid_context(ctx):
    if not bpy.context.active_object \
        or bpy.context.active_object.type != 'ARMATURE' \
        or ctx.mode != 'OBJECT':
        return False
        # Only allow rigs with a "rigify id"
    try:
        return ctx.active_object.data.get("rig_id")
    except (AttributeError, KeyError, TypeError):
        return False


class OBJECT_OT_bake_rigify(bpy.types.Operator):
    bl_label = 'Bake Rigify rig'
    bl_idname = 'object.bake_rigify'

    @classmethod
    def poll(cls, ctx):
        return poll_valid_context(ctx)

    def select_bone(self, armature, bone_name):
        """
        Select bone in armature
        INFO: Operates in EDIT MODE - Ends in OBJECT MODE
        """
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.armature.select_all(action='DESELECT')
        edit_bone = armature.data.edit_bones[bone_name]
        edit_bone.select = True
        bpy.ops.object.mode_set(mode='OBJECT')
        armature.data.bones.active = armature.data.bones[bone_name]
        return armature.data.bones.active

    def duplicate_bone(self):
        """
        Duplicates current bone
        INFO: Operates in EDIT MODE
        """
        bpy.ops.armature.duplicate()
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.mode_set(mode='EDIT')
        duplicated_bone = bpy.context.active_bone
        return duplicated_bone

    def execute(self, ctx):
        # Original Armature
        origArma = bpy.context.active_object
        origArmaName = origArma.name

        # Bake Armature
        bpy.ops.object.duplicate(linked=False)
        bakeArma = bpy.context.active_object
        bakeArmaName = bakeArma.name

        # Make Single User Armature Data (will be modified)
        bpy.ops.object.make_single_user(obdata=True)

        # Move the Bake Armature off to the site for debugging
        # bpy.ops.transform.translate(value=(3, 0, 0))

        # Toggle into edit mode
        bpy.ops.object.mode_set(mode='EDIT')

        # Turn all layers visible for operators to work
        for i in range(0, 32):
            bakeArma.data.layers[i] = True

        # Collect all edit bones
        ebs = bakeArma.data.edit_bones
        defBoneNames = [b.name for b in ebs if b.name.startswith('DEF')]
        for defBoneName in defBoneNames:
            # select bone
            self.select_bone(bakeArma, defBoneName)

            # Duplicate current bone
            bpy.ops.object.mode_set(mode='EDIT')
            duplicated_bone = self.duplicate_bone()
            duplicated_bone.name = "EXP%s" % defBoneName[3:]

            # Process all deformation bones
            duplicated_bone.parent = None

            # Track name for mode changes
            duplicated_bone_name = duplicated_bone.name

            # Toggle to object mode to propagate edit mode changes
            bpy.ops.object.mode_set(mode='OBJECT')

            # Add the constraints
            bpy.ops.object.mode_set(mode='POSE')
            duplicated_pose_bone = bakeArma.pose.bones[duplicated_bone_name]

            c = duplicated_pose_bone.constraints.new(type='COPY_TRANSFORMS')
            c.target = bakeArma
            c.subtarget = defBoneName

        # Select target bones for baking
        bpy.ops.object.mode_set(mode='EDIT')
        ebs = bakeArma.data.edit_bones
        for b in ebs:
            if b.name.startswith('EXP') or b.name == 'root':
                b.select = True
        bpy.ops.object.mode_set(mode='OBJECT')

        # Perform the bake
        # Need to switch the area type (See: http://blenderartists.org/forum/archive/index.php/t-195704.html)
        current_type = ''
        if not bpy.app.background:
            current_type = bpy.context.area.type
            bpy.context.area.type = 'NLA_EDITOR'
        bpy.ops.nla.bake(
            frame_start=bakeArma.animation_data.action.frame_range[0],
            frame_end=bakeArma.animation_data.action.frame_range[1],
            step=1,
            only_selected=True,
            clear_constraints=True,
            bake_types={'POSE'},
        )
        if not bpy.app.background:
            bpy.context.area.type = current_type

        # Set Name for Baked Action
        actnName = origArma.animation_data.action.name
        actnName = actnName[2:] if actnName.startswith('a_') else actnName
        bakeArma.animation_data.action.name = "baked_%s" % actnName

        # Delete all un-selected bones
        bpy.ops.object.mode_set(mode='EDIT')
        ebs = bakeArma.data.edit_bones
        for b in ebs:
            if not b.select:
                ebs.remove(b)

        # Rename EXP-bones back to ``DEF`` so that vertex groups work
        dup_bone_names = []
        for b in ebs:
            b.use_deform = True
            b.name = "DEF%s" % b.name[3:] if not b.name == 'root' else b.name
            dup_bone_names.append(b.name)

        # Remove left-over constraints (nla.bake() may leave residue)
        bpy.ops.object.mode_set(mode='POSE')
        for b in bakeArma.pose.bones:
            [b.constraints.remove(c) for c in b.constraints]

        # Set the layers to what matters only
        for i in range(0, 32):
            bakeArma.data.layers[i] = True if (i in (28, 29)) else False

        # Add static root bone
        # Info: The static root bone is the original root bone's parent that does not move.
        # This avoids ``Delta Translation`` issues
        bpy.context.scene.cursor_location = (0, 0, 0)
        bpy.ops.object.mode_set(mode='EDIT')
        oldRoot = bakeArma.data.edit_bones['root']
        oldRoot.name = 'dummy'
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.armature.bone_primitive_add(name='root')
        oldRoot = bakeArma.data.edit_bones['dummy']
        oldRoot.parent = bakeArma.data.edit_bones['root']

        # Remove all animation from root and dummy
        bpy.ops.object.mode_set(mode='POSE')
        for b in ["root", "dummy"]:
            for f in range(int(bakeArma.animation_data.action.frame_range[1] + 1)):
                bakeArma.keyframe_delete('pose.bones["%s"].scale' % b, index=-1, frame=f)
                bakeArma.keyframe_delete('pose.bones["%s"].location' % b, index=-1, frame=f)
                bakeArma.keyframe_delete('pose.bones["%s"].rotation_euler' % b, index=-1, frame=f)
                bakeArma.keyframe_delete('pose.bones["%s"].rotation_quaternion' % b, index=-1, frame=f)
                bakeArma.keyframe_delete('pose.bones["%s"].rotation_axis_angle' % b, index=-1, frame=f)
            bpy.ops.pose.select_all(action='DESELECT')
            bakeArma.pose.bones[b].bone.select = True
            bpy.ops.pose.loc_clear()
            bpy.ops.pose.scale_clear()
            bpy.ops.pose.rot_clear()

        # Now re-parent all bones to the dummy and then it's done
        bpy.ops.object.mode_set(mode='EDIT')
        dummyEB = bakeArma.data.edit_bones["dummy"]
        for b in dup_bone_names:
            bakeArma.data.edit_bones[b].parent = dummyEB

        bpy.ops.object.mode_set(mode='OBJECT')

        return {'FINISHED'}


class OBJECT_PT_bake_rigify(bpy.types.Panel):
    bl_label = "Rigify Bake"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "data"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, ctx):
        return poll_valid_context(ctx)

    def draw(self, ctx):
        layout = self.layout
        layout.operator('object.bake_rigify')


def register():
    bpy.utils.register_class(OBJECT_OT_bake_rigify)
    bpy.utils.register_class(OBJECT_PT_bake_rigify)


def unregister():
    bpy.utils.unregister_class(OBJECT_PT_bake_rigify)
    bpy.utils.unregister_class(OBJECT_OT_bake_rigify)
