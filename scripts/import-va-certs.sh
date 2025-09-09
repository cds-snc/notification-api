#!/bin/bash

set -euo pipefail

# Install the following VA certs in /usr/local/share/ca-certificates/.
#
# Certificates can arrive in either DER or PEM encoding. All changes
# to this script need to take that into consideration.

(
    cd /usr/local/share/ca-certificates/

    wget \
        --recursive \
        --level=1 \
        --quiet \
        --no-parent \
        --no-host-directories \
        --no-directories \
        --accept="VA*.cer" \
        http://aia.pki.va.gov/PKI/AIA/VA/

    for cert in VA-*.cer
    do
        # Check if the certificate is already in PEM format
        if file "${cert}" | grep 'PEM'
        then
            cp "${cert}" "${cert}.crt"
        else
            # attempt to convert DER to PEM format
            if ! openssl x509 -in "${cert}" -inform der -outform pem -out "${cert}.crt";
            then
                # if that fails, try base64 decode first, then convert
                if ! base64 -d "${cert}" | openssl x509 -inform der -outform pem -out "${cert}.crt"; then
                    echo "Error: Failed to convert ${cert} to .crt file using base64 decode and openssl. Please check the file format. Exiting."
                    exit 1
                fi
            fi
        fi
        rm "${cert}"
    done

    update-ca-certificates --fresh

    # Display VA Internal certificates that are now trusted.
    awk -v cmd='openssl x509 -noout -subject' '/BEGIN/{close(cmd)};{print | cmd}' < /etc/ssl/certs/ca-certificates.crt \
    | grep -i 'VA-Internal'
)
