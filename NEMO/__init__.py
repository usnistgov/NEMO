from django.apps import AppConfig


def init_admin_site():
	from NEMO.views.customization import get_customization
	from django.contrib import admin
	# customize the site
	site_title = get_customization("site_title", raise_exception=False)
	admin.site.site_header = site_title
	admin.site.site_title = site_title
	admin.site.index_title = "Detailed administration"


def init_rates():
	from NEMO.rates import rate_class
	rate_class.load_rates()


class NEMOConfig(AppConfig):
	name = "NEMO"

	def ready(self):
		from django.apps import apps
		if apps.is_installed("django.contrib.admin"):
			init_admin_site()
		init_rates()


default_app_config = "NEMO.NEMOConfig"
