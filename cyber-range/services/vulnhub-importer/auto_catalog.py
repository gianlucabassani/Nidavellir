#!/usr/bin/env python3
"""
VulnHub Catalog Manager
Wrapper around auto_importer to fetch images and tag them for the Cyber Range Randomizer.
"""
import argparse
import logging
import sys
# Import your existing importer class
from auto_importer import VulnHubImporter

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("CatalogManager")

def main():
    parser = argparse.ArgumentParser(description="Import VulnHub VM into Cyber Range Catalog")
    parser.add_argument("url", help="Direct download URL of the VulnHub image (zip/7z/ova)")
    parser.add_argument("--name", required=True, help="Internal name (e.g., 'mr-robot')")
    parser.add_argument("--difficulty", choices=["easy", "medium", "hard"], required=True, help="Difficulty level")
    parser.add_argument("--desc", default="VulnHub Image", help="Short description")
    
    args = parser.parse_args()

    # 1. Define Metadata (The "Catalog" Entry)
    # These properties are what makes the Randomizer work!
    glance_properties = {
        "cyber_range_image": "true",          # Marker for the Orchestrator
        "vulnhub_difficulty": args.difficulty, # 'easy', 'medium', 'hard'
        "description": args.desc,
        "hw_disk_bus": "scsi",                # Optimization for compat
        "hw_scsi_model": "virtio-scsi"
    }

    # 2. Run the Import
    logger.info(f"🚀 Starting Catalog Import: {args.name} [{args.difficulty}]")
    importer = VulnHubImporter()
    
    # We pass 'SKIP' to checksum if you don't have it handy, 
    # BUT you must update auto_importer.py to handle "SKIP" as discussed before.
    result = importer.import_from_url(
        url=args.url,
        image_name=args.name,
        sha256="SKIP", 
        metadata=glance_properties
    )

    if result['success']:
        logger.info(f"✅ Image added to Catalog! ID: {result.get('openstack_image_id')}")
        logger.info("   Run 'tofu apply' with this difficulty to test.")
    else:
        logger.error(f"❌ Import failed: {result.get('error')}")
        sys.exit(1)

if __name__ == "__main__":
    main()