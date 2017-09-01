from distutils.core import setup

setup(
	name='NEMO',
	version='0.1',
	packages=['NEMO'],
	url='https://github.com/usnistgov/NEMO',
	license='Public domain',
	author='Dylan Klomparens',
	author_email='dylan.klomparens@nist.gov',
	description='NEMO is a laboratory logistics web application. Use it to schedule reservations, control tool access, track maintenance issues, and more.',
	install_requires=[
		'Django',
		'django-filter',
		'djangorestframework',
		'ldap3',
		'pyasn1',
		'python-dateutil',
		'pytz',
		'Gunicorn',
		'requests',
		'Pillow',
	],
)
