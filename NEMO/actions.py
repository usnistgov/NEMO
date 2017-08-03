def lock_selected_interlocks(model_admin, request, queryset):
	for interlock in queryset:
		interlock.lock()


def unlock_selected_interlocks(model_admin, request, queryset):
	for interlock in queryset:
		interlock.unlock()
