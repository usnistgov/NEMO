from socket import gethostbyname_ex, gaierror
from socket import error as socket_error
from _ssl import CERT_REQUIRED, PROTOCOL_TLSv1_2
from getpass import getpass
from os import remove
from ssl import get_server_certificate
from subprocess import run
from sys import argv
from textwrap import dedent

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from cryptography.x509 import NameAttribute, NameOID, DNSName, CertificateSigningRequestBuilder, Name, SubjectAlternativeName
from django.utils.crypto import get_random_string
from ldap3 import Tls, Server, Connection, AUTO_BIND_TLS_BEFORE_BIND, SIMPLE
from ldap3.core.exceptions import LDAPBindError, LDAPExceptionError


def entry_point():
	request = argv[1] if len(argv) == 2 else None
	if request == 'generate_secret_key':
		generate_secret_key()
	elif request == 'query_public_key':
		query_public_key()
	elif request == 'test_ldap_authentication':
		test_ldap_authentication()
	elif request == 'generate_tls_keys':
		generate_tls_keys()
	elif request == 'install_systemd_service':
		install_systemd_service()
	elif request == 'uninstall_systemd_service':
		uninstall_systemd_service()
	elif request == 'open_firewall_ports':
		open_firewall_ports()
	else:
		usage = \
				"""
				You can provision everything NEMO needs to run with these commands...
				
				generate_secret_key -
					Prints a randomly generated secret key, used for hashing user sessions,
					cryptographic signing, and more. More information is available from the Django documentation:
					https://docs.djangoproject.com/en/1.11/ref/settings/#std:setting-SECRET_KEY
				
				query_public_key -
					Opens a TLS connection to another server and prints the public TLS key.
					This is useful if you want to verify correct TLS configuration,
					or pin a particular certificate for LDAPS authentication.
				
				test_ldap_authentication -
					Opens an encrypted connection (using only TLS 1.2) to an LDAP directory (such as Active Directory)
					and tests authentication. You will be prompted for the hostname of the authentication server,
					the domain name, a username, password, and public TLS key.
				
				generate_tls_keys -
					Generates an RSA 4096 bit private key and certificate signing request. These can be used
					to obtain a public key, enabling TLS encryption for your NEMO users. This keeps communication
					between a user's web browser and the NEMO server secure.
				
				install_systemd_service -
					Installs NEMO as a service with Systemd (by creating a file /etc/systemd/system/nemo.service).
					After running this command you can manipulate NEMO with standard systemctl commands, such as:
					systemctl start nemo
					systemctl stop nemo
					systemctl restart nemo
					systemctl enable nemo
					systemctl disable nemo
					See this tutorial on Systemd for more information:
					https://www.digitalocean.com/community/tutorials/how-to-use-systemctl-to-manage-systemd-services-and-units
				
				uninstall_systemd_service -
					Uninstalls NEMO as a service with Systemd (by simply deleting /etc/systemd/system/nemo.service).
				
				open_firewall_ports -
					Configure the firewall to allow incoming web browser requests.
					Requests received on port 80 are intended to be redirected to port 443 for improved security.
					Port 80 (HTTP) and 443 (HTTPS) are made available via firewall-cmd:
					firewall-cmd --zone=public --permanent --add-service=http
					firewall-cmd --zone=public --permanent --add-service=https
				"""
		print(dedent(usage))


def generate_secret_key():
	"""
	Writes a new Django secret key to the specified file. Use this with your settings.py file for hashing and signing.
	Documentation available at https://docs.djangoproject.com/en/1.11/ref/settings/#std:setting-SECRET_KEY
	"""
	print(get_random_string(50, "abcdefghijklmnopqrstuvwxyz0123456789!@$%&=-+#(*_^)"))


def query_public_key():
	"""
	Opens a secure connection to a server and downloads its public TLS key.
	The key is printed in PEM format.
	"""
	print("Query a server's public TLS key.")
	print("If the DNS name resolves to multiple IP addresses then the public keys for all IP addresses are printed.")
	print("Port 636 is commonly used for secure LDAP.")
	print("Port 443 is commonly used for secure HTTP.")
	name = input("DNS name or IP address = ")
	port = input("Port = ")

	try:
		ip_addresses = gethostbyname_ex(name)[2]
	except gaierror:
		print('DNS name resolution failed.')
		return
	except socket_error as e:
		print(f'Socket error: {e}')
		return

	if len(ip_addresses) == 0:
		print('No IP address was returned from DNS name resolution.')
	elif len(ip_addresses) == 1:
		try:
			certificate = get_server_certificate((name, port))
			print(certificate)
		except socket_error as e:
			print(f'Socket error: {e}')
			return
	elif len(ip_addresses) > 1:
		print(f"Name resolves to {len(ip_addresses)} IP addresses: {ip_addresses}")
		for ip in ip_addresses:
			print(f"Querying certificate for {ip}:")
			try:
				certificate = get_server_certificate((ip, port))
				print(certificate)
			except socket_error as e:
				print(f'Socket error: {e}')


def test_ldap_authentication():
	""" Opens an encrypted connection (using only TLS 1.2) to an LDAP directory (such as Active Directory) and tests authentication """
	name = input("DNS name or IP address = ")
	domain = input("Domain = ")
	username = input("Username = ")
	password = getpass("Password = ")
	certificate = input("Path to public key certificate = ")
	try:
		t = Tls(validate=CERT_REQUIRED, version=PROTOCOL_TLSv1_2, ca_certs_file=certificate)
		s = Server(name, port=636, use_ssl=True, tls=t)
		c = Connection(s, user='{}\\{}'.format(domain, username), password=password, auto_bind=AUTO_BIND_TLS_BEFORE_BIND, authentication=SIMPLE)
		c.unbind()
		# At this point the user successfully authenticated to at least one LDAP server.
		print("Authentication successful!")
	except LDAPBindError as e:
		pass  # When this error is caught it means the username and password were invalid against the LDAP server.
	except LDAPExceptionError as e:
		print("A problem was encountered during authentication:\n")
		print(e)


def generate_tls_keys():
	""" Creates a TLS private key (RSA, 4096 bits, PEM format) and certificate signing request (CSR). """

	# Query the user for CSR attributes
	country = input("Country: ")
	state = input("State or province: ")
	locality = input("Locality: ")
	organization = input("Organization: ")
	organizational_unit = input("Organizational unit: ")
	email = input("Email: ")
	common_name = input("Common name: ")

	print("Enter any subject alternative names (SANs) you wish to attach to the certificate. Leave blank to continue.")
	sans = []
	while True:
		san = input("Subject alternative name: ")
		if san == '':
			break
		sans.append(DNSName(san))

	# Make sure we can open the output files first
	private_key_file = open("private.key", "wb")
	csr_file = open("certificate_signing_request", "wb")

	# Generate the private key
	key = generate_private_key(public_exponent=65537, key_size=4096, backend=default_backend())

	attributes = [
		NameAttribute(NameOID.COUNTRY_NAME, country),
		NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, state),
		NameAttribute(NameOID.LOCALITY_NAME, locality),
		NameAttribute(NameOID.ORGANIZATION_NAME, organization),
		NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, organizational_unit),
		NameAttribute(NameOID.EMAIL_ADDRESS, email),
		NameAttribute(NameOID.COMMON_NAME, common_name),
	]

	# Generate the CSR and sign it with the private key
	csr = CertificateSigningRequestBuilder().subject_name(Name(attributes))
	if sans:
		csr = csr.add_extension(SubjectAlternativeName(sans), critical=False)
	csr = csr.sign(key, SHA256(), default_backend())

	# Write the private key and CSR to disk
	private_key_file.write(key.private_bytes(encoding=Encoding.PEM, format=PrivateFormat.TraditionalOpenSSL, encryption_algorithm=NoEncryption()))
	csr_file.write(csr.public_bytes(Encoding.PEM))

	private_key_file.close()
	csr_file.close()

	# Success!
	print("Successfully generated a private key and certificate signing request.")


def install_systemd_service():
	""" Installs NEMO as a systemd service. """
	customizations = {
		'user': 'nemo',
		'group': 'nemo',
		'process_identifier_file': '/tmp/nemo.pid',
		'gunicorn': '/home/nemo/python/bin/gunicorn',
	}

	service = """
	[Unit]
	Description=NEMO is a laboratory logistics web application. Use it to schedule reservations, control tool access, track maintenance issues, and more.
	After=network.target syslog.target nss-lookup.target

	[Service]
	User={user}
	Group={group}
	PIDFile={process_identifier_file}
	ExecStart={gunicorn} NEMO.wsgi:application
	ExecReload=/bin/kill -s HUP $MAINPID
	ExecStop=/bin/kill -s TERM $MAINPID
	PrivateTmp=true

	[Install]
	WantedBy=multi-user.target
	""".format(**customizations)

	with open('/etc/systemd/system/nemo.service', 'w') as f:
		f.write(dedent(service))

	print("The systemd NEMO service was successfully installed.")


def uninstall_systemd_service():
	""" Uninstalls NEMO as a systemd service """
	remove('/etc/systemd/system/nemo.service')
	print("The systemd NEMO service was successfully uninstalled.")


def open_firewall_ports():
	http_result = run(['firewall-cmd', '--zone=public', '--permanent', '--add-service=http'])
	https_result = run(['firewall-cmd', '--zone=public', '--permanent', '--add-service=https'])
	reload_result = run(['firewall-cmd', '--reload'])


if __name__ == "__main__":
	entry_point()
