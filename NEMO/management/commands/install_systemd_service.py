from textwrap import dedent

from django.core.management import BaseCommand


class Command(BaseCommand):
	help = "Installs NEMO as a systemd service"

	def handle(self, file_name):
		try:
			customizations = {
				'user': 'nemo',
				'group': 'nemo',
				'process_identifier_file': '/tmp/nemo.pid',
				'gunicorn': '/bin/gunicorn',
				'nemo_source_directory': '/sites/nemo',
			}

			service = """
			[Unit]
			Description=NEMO is a laboratory logistics web application. Use it to schedule reservations, control tool access, track maintenance issues, and more.
			After=network.target syslog.target nss-lookup.target

			[Service]
			User={user}
			Group={group}
			PIDFile={process_identifier_file}
			ExecStart={gunicorn} --chdir {nemo_source_directory} --bind 127.0.0.1:9000 wsgi:application
			ExecReload=/bin/kill -s HUP $MAINPID
			ExecStop=/bin/kill -s TERM $MAINPID
			PrivateTmp=true

			[Install]
			WantedBy=multi-user.target
			""".format(**customizations)

			with open('/etc/systemd/system/nemo.service', 'w') as f:
				f.write(dedent(service))

			self.stdout.write(self.style.SUCCESS("The systemd NEMO service was successfully installed"))
		except Exception as e:
			self.stderr.write(self.style.ERROR("Something went wrong: " + str(e)))
