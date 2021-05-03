from django.contrib import messages
from django.urls import reverse
from django.utils.safestring import mark_safe

from NEMO.models import User, Area, Tool


def lock_selected_interlocks(model_admin, request, queryset):
	for interlock in queryset:
		try:
			interlock.lock()
			messages.success(request, f"{interlock} has been successfully locked")
		except Exception as error:
			messages.error(request, f"{interlock} could not be locked due to the following error: {str(error)}")


def unlock_selected_interlocks(model_admin, request, queryset):
	for interlock in queryset:
		try:
			interlock.unlock()
			messages.success(request, f"{interlock} has been successfully unlocked")
		except Exception as error:
			messages.error(request, f"{interlock} could not be unlocked due to the following error: {str(error)}")


def synchronize_with_tool_usage(model_admin, request, queryset):
	for interlock in queryset:
		# Ignore interlocks with no tool assigned, and ignore interlocks connected to doors
		if not hasattr(interlock, "tool") or hasattr(interlock, "door"):
			continue
		if interlock.tool.in_use():
			interlock.unlock()
		else:
			interlock.lock()


def duplicate_tool_configuration(model_admin, request, queryset):
	for tool in queryset:
		original_name = tool.name
		new_name = "Copy of " + tool.name
		try:
			if Tool.objects.filter(name=new_name).exists():
				messages.error(
					request,
					mark_safe(
						f'There is already a copy of {original_name} as <a href="{reverse("admin:NEMO_tool_change", args=[tool.id])}">{new_name}</a>. Change the copy\'s name and try again'
					),
				)
				continue
			elif tool.is_child_tool():
				messages.warning(request, f"{original_name} is a child tool and cannot be duplicated")
				continue
			else:
				old_required_resources = tool.required_resource_set.all()
				old_nonrequired_resources = tool.nonrequired_resource_set.all()
				old_backup_users = tool.backup_owners.all()
				old_superusers = tool.superusers.all()
				old_qualified_users = User.objects.filter(qualifications__id=tool.pk).distinct()
				tool.pk = None
				tool.interlock = None
				tool.visible = False
				tool.operational = False
				tool.name = new_name
				tool.image = None
				tool.description = None
				tool.serial = None
				tool.save()
				tool.required_resource_set.set(old_required_resources)
				tool.nonrequired_resource_set.set(old_nonrequired_resources)
				tool.backup_owners.set(old_backup_users)
				tool.superusers.set(old_superusers)
				for user in old_qualified_users:
					user.qualifications.add(tool)
				messages.success(
					request,
					mark_safe(
						f'A duplicate of {original_name} has been made as <a href="{reverse("admin:NEMO_tool_change", args=[tool.id])}">{tool.name}</a>'
					),
				)
		except Exception as error:
			messages.error(
				request, f"{original_name} could not be duplicated because of the following error: {str(error)}"
			)


def rebuild_area_tree(model_admin, request, queryset):
	Area.objects.rebuild()
