import os
import datetime
from OpenSSL import crypto
from datadog_checks.base import AgentCheck


# https://docs.datadoghq.com/developers/custom_checks/write_agent_check/ for info on how custom checks work
class CertExpirationCheck(AgentCheck):
    def check(self, instance):
        # Directory where our non-ACM certificates reside
        cert_dir = instance.get('cert_dir', '/usr/local/share/ca-certificates/')

        if not os.path.isdir(cert_dir):
            self.log.error('Certificate directory %s does not exist.', cert_dir)
            return

        for filename in os.listdir(cert_dir):
            if filename.endswith('.crt'):
                cert_path = os.path.join(cert_dir, filename)
                try:
                    with open(cert_path, 'rb') as cert_file:
                        cert_data = cert_file.read()

                    # Load the certificate (PEM format)
                    cert = crypto.load_certificate(crypto.FILETYPE_PEM, cert_data)

                    # Get the notAfter field, which is in the format "YYYYMMDDHHMMSSZ"
                    not_after = cert.get_notAfter().decode('utf-8')
                    expiry_date = datetime.datetime.strptime(not_after, '%Y%m%d%H%M%SZ')
                    now = datetime.datetime.utcnow()

                    # Calculate days remaining until expiration
                    days_remaining = (expiry_date - now).days

                    # Emit a gauge metric with the certificate name as a tag
                    self.gauge('certificates.days_to_expire', days_remaining, tags=[f'certificate:{filename}'])

                    self.log.debug('Certificate %s expires in %s days.', filename, days_remaining)

                except Exception as e:
                    self.log.error('Error processing certificate %s: %s', filename, str(e))
