from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from cryptography.x509 import NameAttribute, NameOID, DNSName, CertificateSigningRequestBuilder, Name, SubjectAlternativeName
from django.core.management import BaseCommand


class Command(BaseCommand):
	help = "Creates a TLS private key (RSA, 4096 bits, PEM format) and certificate signing request (CSR)."

	def handle(self, *positional_arguments, **named_arguments):
		try:
			# Query the user for CSR attributes
			country = input("Country: ")
			state = input("State or province: ")
			locality = input("Locality: ")
			organization = input("Organization: ")
			organizational_unit = input("Organizational unit: ")
			email = input("Email: ")
			common_name = input("Common name: ")

			self.stdout.write("Enter any subject alternative names (SANs) you wish to attach to the certificate. Leave blank to continue.")
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
			self.stdout.write(self.style.SUCCESS("Successfully generated a private key and certificate signing request."))

		except Exception as e:
			self.stderr.write(self.style.ERROR("Something went wrong: " + str(e)))
