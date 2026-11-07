#!/usr/bin/env python3
"""Render only; never applies a manifest or changes application routing."""
import argparse
from pathlib import Path
import re

parser = argparse.ArgumentParser()
parser.add_argument('image')
args = parser.parse_args()
if not re.fullmatch(r'ghcr\.io/shopify/toxiproxy@sha256:[a-f0-9]{64}', args.image):
    parser.error('Se requiere ghcr.io/shopify/toxiproxy@sha256:DIGEST')
print((Path(__file__).parent / 'k8s/proxy.yaml').read_text().replace('TOXIPROXY_IMAGE', args.image), end='')
