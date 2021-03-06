# --------------------------------------------------------------------------
#
# Copyright (c) Microsoft Corporation. All rights reserved.
#
# The MIT License (MIT)
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the ""Software""), to
# deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
# sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED *AS IS*, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.
#
# --------------------------------------------------------------------------

import os
import json
import logging

from adal import AuthenticationContext
from azure.keyvault.key_vault_client import KeyVaultClient
from msrestazure.azure_active_directory import AdalAuthentication

logging.basicConfig(level=logging.INFO,
                    format='|%(asctime)s|%(levelname)-5s|%(process)d|%(thread)d|%(name)s|%(message)s')

_logger = logging.getLogger('keyvault-agent')

AZURE_AUTHORITY_SERVER = os.getenv('AZURE_AUTHORITY_SERVER', 'https://login.microsoftonline.com/')
VAULT_RESOURCE_NAME = os.getenv('VAULT_RESOURCE_NAME', 'https://vault.azure.net')


class KeyVaultAgent(object):
    """
    A Key Vault agent that reads secrets from Key Vault and stores them in a folder
    """

    def __init__(self):
        self._parse_sp_file()
        self._secrets_output_folder = None
        self._certs_output_folder = None
        self._keys_output_folder = None

    def _parse_sp_file(self):
        file_path = os.getenv('SERVICE_PRINCIPLE_FILE_PATH')
        _logger.info('Parsing Service Principle file from: %s', file_path)
        if not os.path.isfile(file_path):
            raise Exception("Service Principle file doesn't exist: %s" % file_path)

        with open(file_path, 'r') as sp_file:
            sp_data = json.load(sp_file)
            # retrieve the relevant values used to authenticate with Key Vault
            self.tenant_id = sp_data['tenantId']
            self.client_id = sp_data['aadClientId']
            self.client_secret = sp_data['aadClientSecret']

        _logger.info('Parsing Service Principle file completed')

    def _get_client(self):
        authority = '/'.join([AZURE_AUTHORITY_SERVER.rstrip('/'), self.tenant_id])
        _logger.info('Using authority: %s', authority)
        context = AuthenticationContext(authority)
        _logger.info('Using vault resource name: %s and client id: %s', VAULT_RESOURCE_NAME, self.client_id)
        credentials = AdalAuthentication(context.acquire_token_with_client_credentials, VAULT_RESOURCE_NAME,
                                         self.client_id, self.client_secret)
        return KeyVaultClient(credentials)

    def grab_secrets(self):
        """
        Gets secrets from KeyVault and stores them in a folder
        """
        vault_base_url = os.getenv('VAULT_BASE_URL')
        secrets_keys = os.getenv('SECRETS_KEYS')
        certs_keys = os.getenv('CERTS_KEYS')
        output_folder = os.getenv('SECRETS_FOLDER')
        self._secrets_output_folder = os.path.join(output_folder, "secrets")
        self._certs_output_folder = os.path.join(output_folder, "certs")
        self._keys_output_folder = os.path.join(output_folder, "keys")

        for folder in (self._secrets_output_folder, self._certs_output_folder, self._keys_output_folder):
            if not os.path.exists(folder):
                os.makedirs(folder)

        client = self._get_client()
        _logger.info('Using vault: %s', vault_base_url)

        if secrets_keys is not None:
            for key_info in filter(None, secrets_keys.split(';')):
                key_name, _, key_version = key_info.strip().partition(':')
                _logger.info('Retrieving secret name:%s with version: %s', key_name, key_version)
                secret = client.get_secret(vault_base_url, key_name, key_version)
                output_path = os.path.join(self._secrets_output_folder, key_name)
                if secret.kid is not None:
                    _logger.info('Secret is backing certificate. Dumping private key and certificate.')
                    self._dump_pfx(secret.value, key_name)
                _logger.info('Dumping secret value to: %s', output_path)
                with open(output_path, 'w') as secret_file:
                    secret_file.write(secret.value)

        if certs_keys is not None:
            for key_info in filter(None, certs_keys.split(';')):
                key_name, _, key_version = key_info.strip().partition(':')
                _logger.info('Retrieving cert name:%s with version: %s', key_name, key_version)
                cert = client.get_certificate(vault_base_url, key_name, key_version)
                output_path = os.path.join(self._certs_output_folder, key_name)
                _logger.info('Dumping cert value to: %s', output_path)
                with open(output_path, 'w') as cert_file:
                    cert_file.write(self._cert_to_pem(cert.cer))

    def _dump_pfx(self, pfx, name):
        import base64
        from OpenSSL import crypto
        p12 = crypto.load_pkcs12(base64.decodestring(pfx))
        pk = crypto.dump_privatekey(crypto.FILETYPE_PEM, p12.get_privatekey())
        cert = crypto.dump_certificate(crypto.FILETYPE_PEM, p12.get_certificate())
        with open(os.path.join(self._keys_output_folder, name), 'w') as key_file:
            key_file.write(pk)
        with open(os.path.join(self._certs_output_folder, name), 'w') as cert_file:
            cert_file.write(cert)

    @staticmethod
    def _cert_to_pem(cert):
        import base64
        encoded = base64.encodestring(cert)
        if isinstance(encoded, bytes):
            encoded = encoded.decode("utf-8")
        encoded = '-----BEGIN CERTIFICATE-----\n' + encoded + '-----END CERTIFICATE-----\n'

        return encoded


if __name__ == '__main__':
    _logger.info('Grabbing secrets from Key Vault')
    KeyVaultAgent().grab_secrets()
    _logger.info('Done!')
