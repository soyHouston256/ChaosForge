#!/usr/bin/env python3
"""Render a manifest pinned to an immutable image. Does not contact the cluster."""
import argparse
from pathlib import Path
import re
parser = argparse.ArgumentParser()
parser.add_argument('image', help='Artifact Registry image with @sha256 digest')
args = parser.parse_args()
# The project is taken from the image reference, so no account is hardcoded here.
match = re.fullmatch(r'us-central1-docker\.pkg\.dev/([a-z][a-z0-9-]{4,28}[a-z0-9])/[a-z0-9_-]+/chaosforge-admin@sha256:[a-f0-9]{64}', args.image)
if not match:
    parser.error('Use us-central1-docker.pkg.dev/PROJECT/REPOSITORY/chaosforge-admin@sha256:DIGEST')
manifest = (Path(__file__).parent/'k8s/admin.yaml').read_text()
print(manifest.replace('CHAOSFORGE_ADMIN_IMAGE', args.image).replace('CHAOSFORGE_GCP_PROJECT', match.group(1)), end='')
