"""
VulnHub Auto-Importer - Minimal
Downloads, converts, and imports vulnerable VM images from VulnHub to OpenStack.
Simple version with essential functionality only.
"""

import os
import json
import subprocess
import hashlib
import logging
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass
import tarfile
import zipfile

try:
    import requests
except ImportError:
    requests = None

try:
    import openstack
except ImportError:
    openstack = None

logger = logging.getLogger(__name__)


@dataclass
class VulnHubMetadata:
    """Metadata for VulnHub images"""
    name: str
    vulnhub_id: str
    url: str
    sha256: str
    upload_date: str
    openstack_image_id: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps({
            'name': self.name,
            'vulnhub_id': self.vulnhub_id,
            'url': self.url,
            'sha256': self.sha256,
            'upload_date': self.upload_date,
            'openstack_image_id': self.openstack_image_id
        })


class VulnHubDownloader:
    """Download VulnHub images with retry and validation"""

    def __init__(self, temp_dir: Optional[str] = None):
        if temp_dir:
            self.temp_dir = Path(temp_dir)
            self.temp_dir.mkdir(parents=True, exist_ok=True)
        else:
            # mkdtemp = private mode-0700 dir; avoids the predictable,
            # world-shared /tmp/vulnhub path (bandit B108).
            self.temp_dir = Path(tempfile.mkdtemp(prefix="vulnhub-"))

    def download(self, url: str, expected_sha256: str, max_retries: int = 3) -> Path:
        """Download file with checksum validation"""
        if not requests:
            raise RuntimeError("requests library required for downloads")

        filename = url.split('/')[-1]
        filepath = self.temp_dir / filename

        for attempt in range(max_retries):
            try:
                logger.info(f"Downloading {filename} (attempt {attempt + 1}/{max_retries})")
                response = requests.get(url, timeout=300, stream=True)
                response.raise_for_status()

                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

                if self._validate_checksum(filepath, expected_sha256):
                    logger.info(f"✓ Download complete: {filepath}")
                    return filepath
                else:
                    logger.error(f"Checksum mismatch for {filename}")
                    filepath.unlink()
            except Exception as e:
                logger.error(f"Download failed: {e}")
                if filepath.exists():
                    filepath.unlink()

        raise RuntimeError(f"Failed to download {url} after {max_retries} attempts")

    def _validate_checksum(self, filepath: Path, expected_sha256: str) -> bool:
        """Validate file checksum"""
        sha256_hash = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest().lower() == expected_sha256.lower()

    def extract_archive(self, archive_path: Path) -> Path:
        """Extract tar or zip archive"""
        extract_dir = self.temp_dir / archive_path.stem
        extract_dir.mkdir(parents=True, exist_ok=True)

        try:
            if archive_path.suffix == '.gz' or archive_path.name.endswith('.tar.gz'):
                with tarfile.open(archive_path, 'r:gz') as tar:
                    # VulnHub archives are untrusted downloads: the 'data'
                    # filter (PEP 706) rejects path traversal, links and
                    # device nodes — bandit just doesn't recognize it yet.
                    tar.extractall(path=extract_dir, filter='data')  # nosec B202
            elif archive_path.suffix == '.zip':
                with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                    # ZipFile.extractall sanitizes member paths itself, but
                    # reject absolute/parent paths explicitly anyway.
                    for member in zip_ref.namelist():
                        if member.startswith(('/', '..')) or '..' in Path(member).parts:
                            raise ValueError(f"Unsafe path in archive: {member}")
                    # Members validated above + ZipFile sanitizes paths itself.
                    zip_ref.extractall(path=extract_dir)  # nosec B202
            else:
                raise ValueError(f"Unsupported archive format: {archive_path.suffix}")

            logger.info(f"✓ Extracted to {extract_dir}")
            return extract_dir
        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            raise


class ImageConverter:
    """Convert VM images to QCOW2 format"""

    def __init__(self):
        self.check_qemu_img()

    def check_qemu_img(self):
        """Verify qemu-img is installed"""
        try:
            subprocess.run(['qemu-img', '--version'], capture_output=True, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            raise RuntimeError("qemu-img not found. Install qemu-utils.")

    def convert_to_qcow2(self, source_path: Path, output_path: Path) -> Path:
        """Convert image to QCOW2"""
        try:
            logger.info(f"Converting {source_path.name} to QCOW2...")
            cmd = ['qemu-img', 'convert', '-f', 'auto', '-O', 'qcow2', str(source_path), str(output_path)]
            subprocess.run(cmd, check=True, capture_output=True)
            logger.info(f"✓ Conversion complete: {output_path}")
            return output_path
        except subprocess.CalledProcessError as e:
            logger.error(f"Conversion failed: {e.stderr.decode()}")
            raise RuntimeError(f"Image conversion failed: {e}")


class OpenStackUploader:
    """Upload images to OpenStack Glance"""

    def __init__(self):
        if not openstack:
            raise RuntimeError("openstacksdk required for uploads")
        self.conn = self._init_connection()

    def _init_connection(self):
        """Initialize OpenStack connection from environment"""
        return openstack.connect(
            auth_url=os.getenv('OS_AUTH_URL'),
            project_name=os.getenv('OS_PROJECT_NAME'),
            username=os.getenv('OS_USERNAME'),
            password=os.getenv('OS_PASSWORD'),
            region_name=os.getenv('OS_REGION_NAME'),
            identity_api_version='3'
        )

    def upload_image(self, image_path: Path, image_name: str, metadata: Dict[str, Any] = None) -> str:
        """Upload image to Glance"""
        try:
            logger.info(f"Uploading {image_name} to Glance...")
            # The SDK reads the file itself via filename= — no open handle needed.
            image = self.conn.image.create_image(
                name=image_name,
                filename=str(image_path),
                disk_format='qcow2',
                container_format='bare',
                is_public=False,
                **metadata or {}
            )
            logger.info(f"✓ Upload complete: {image.id}")
            return image.id
        except Exception as e:
            logger.error(f"Upload failed: {e}")
            raise


class VulnHubImporter:
    """Orchestrate full import pipeline: download → convert → upload"""

    def __init__(self):
        self.downloader = VulnHubDownloader()
        self.converter = ImageConverter()
        try:
            self.uploader = OpenStackUploader()
        except RuntimeError:
            logger.warning("OpenStack not configured - upload disabled")
            self.uploader = None

    def import_from_url(self, url: str, image_name: str, sha256: str, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """Download, convert, and upload image"""
        try:
            # Download
            archive_path = self.downloader.download(url, sha256)

            # Extract
            extract_dir = self.downloader.extract_archive(archive_path)

            # Find image file
            image_file = self._find_image_file(extract_dir)
            if not image_file:
                raise RuntimeError(f"No VM image found in {extract_dir}")

            # Convert to QCOW2
            qcow2_path = extract_dir / f"{image_name}.qcow2"
            self.converter.convert_to_qcow2(image_file, qcow2_path)

            # Upload
            result = {
                'success': False,
                'image_name': image_name,
                'local_path': str(qcow2_path),
                'openstack_image_id': None
            }

            if self.uploader:
                image_id = self.uploader.upload_image(qcow2_path, image_name, metadata or {})
                result['openstack_image_id'] = image_id
                result['success'] = True
            else:
                result['success'] = True
                logger.info("Local conversion complete (OpenStack upload skipped)")

            return result

        except Exception as e:
            logger.error(f"Import failed: {e}")
            return {'success': False, 'error': str(e), 'image_name': image_name}

    def _find_image_file(self, directory: Path) -> Optional[Path]:
        """Find first VM image file in directory"""
        image_extensions = ['.vmdk', '.qcow2', '.vdi', '.img', '.raw']
        for root, dirs, files in os.walk(directory):
            for file in files:
                if any(file.endswith(ext) for ext in image_extensions):
                    return Path(root) / file
        return None
