from NEMO.models import User, Area


def lock_selected_interlocks(model_admin, request, queryset):
	for interlock in queryset:
		interlock.lock()


def unlock_selected_interlocks(model_admin, request, queryset):
	for interlock in queryset:
		interlock.unlock()


def synchronize_with_tool_usage(model_admin, request, queryset):
	for interlock in queryset:
		# Ignore interlocks with no tool assigned, and ignore interlocks connected to doors
		if not hasattr(interlock, 'tool') or hasattr(interlock, 'door'):
			continue
		if interlock.tool.in_use():
			interlock.unlock()
		else:
			interlock.lock()

def duplicate_tool_configuration(model_admin, request, queryset):
	for tool in queryset:
		if not tool.is_child_tool():
			old_required_resources = tool.required_resource_set.all()
			old_nonrequired_resources = tool.nonrequired_resource_set.all()
			old_backup_users = tool.backup_owners.all()
			old_qualified_users = User.objects.filter(qualifications__id=tool.pk).distinct()
			tool.pk = None
			tool.interlock = None
			tool.visible = False
			tool.operational = False
			tool.name = 'Copy of '+tool.name
			tool.image = None
			tool.description = None
			tool.serial = None
			tool.save()
			tool.required_resource_set.set(old_required_resources)
			tool.nonrequired_resource_set.set(old_nonrequired_resources)
			tool.backup_owners.set(old_backup_users)
			for user in old_qualified_users:
				user.qualifications.add(tool)

def rebuild_area_tree(model_admin, request, queryset):
	Area.objects.rebuild()