#!/usr/bin/env python3
"""Render a manifest pinned to an immutable image. Does not contact the cluster."""
import argparse
from pathlib import Path
import re
parser = argparse.ArgumentParser()
parser.add_argument('image', help='Artifact Registry image with @sha256 digest')
args = parser.parse_args()
if not re.fullmatch(r'us-central1-docker\.pkg\.dev/tider-ops/[a-z0-9_-]+/chaosforge-admin@sha256:[a-f0-9]{64}', args.image):
    parser.error('Use us-central1-docker.pkg.dev/tider-ops/REPOSITORY/chaosforge-admin@sha256:DIGEST')
print((Path(__file__).parent/'k8s/admin.yaml').read_text().replace('CHAOSFORGE_ADMIN_IMAGE', args.image), end='')
