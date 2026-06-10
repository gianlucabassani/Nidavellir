import subprocess
import logging
import shutil
import json
import os
import time
from pathlib import Path
from config import BASE_TERRAFORM_TEMPLATE, RUNS_DIR, TEMPLATES_DIR

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Orchestrator:
    def __init__(self):
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        self.mock_mode = os.getenv("MOCK_MODE", "false").lower() == "true"

    def _prepare_workspace(self, instance_id: str) -> Path:
        work_dir = RUNS_DIR / instance_id
        if work_dir.exists(): 
            shutil.rmtree(work_dir)
        shutil.copytree(BASE_TERRAFORM_TEMPLATE, work_dir)
        
        # Backend ovveride ensures each lab has its own terraform.tfstate file
        backend_override = work_dir / "backend_override.tf"
        backend_override.write_text('''
    terraform {
    backend "local" {
        path = "terraform.tfstate"
    }
    }
    ''')
    
        logger.info(f"[{instance_id}] Workspace prepared at {work_dir}")
        return work_dir

    def deploy(self, scenario_name: str, instance_id: str, user_vars: dict = None):
        logger.info(f"[{instance_id}] Starting deployment of scenario '{scenario_name}' (Mock Mode: {self.mock_mode})")        
        
        if self.mock_mode:
            logger.info(f"[{instance_id}] 🎭 SIMULATING DEPLOY...")
            time.sleep(2)
            
            # --- MOCK DATA MATCHING DASHBOARD.HTML ---
            fake_outputs = {
                "soc_dashboard_url": "https://192.168.1.50:443",
                "soc_credentials": {"username": "admin", "password": "SecretPassword!"},
                "log_vm_ssh_command": "ssh ubuntu@192.168.1.50",
                "log_vm_private_ip": "192.168.0.5",
                "log_vm_floating_ip": "192.168.1.50",
                
                "attack_vm_ssh_command": "ssh kali@192.168.1.80",
                "attack_vm_private_ip": "192.168.50.10",
                "attack_vm_floating_ip": "192.168.1.80",
                
                "victim_vm_private_ip": "192.168.0.10",
                "victim_vm_floating_ip": "192.168.1.60"
            }
            return {"success": True, "outputs": fake_outputs}
        
        

        # REAL LOGIC
        work_dir = None
        try:
            # READ SCENARIO CONFIGURATION
            scenario_config = self._load_scenario(scenario_name)
            if not scenario_config:
                return {
                    "success": False,
                    "error": f"Scenario '{scenario_name}' not found"
                }
            work_dir = self._prepare_workspace(instance_id)

            # STEP 1: TERRAFORM INIT (with retry)
            logger.info(f"[{instance_id}] Running terraform init...")
            for attempt in range(3):
                try:
                    result = subprocess.run(
                        ["tofu", "init"], 
                        cwd=work_dir, 
                        check=True, 
                        capture_output=True,
                        text=True,
                        timeout=300  # 5 min timeout
                    )
                    logger.info(f"[{instance_id}] Init successful")
                    break

                except subprocess.TimeoutExpired:
                    if attempt == 2:
                        raise RuntimeError("Terraform init timed out after 3 attempts")
                    logger.warning(f"[{instance_id}] Init timeout, retry {attempt+1}/3")
                    time.sleep(5)
                except subprocess.CalledProcessError as e:
                    if attempt == 2:
                        raise RuntimeError(f"Init failed: {e.stderr}")
                    time.sleep(5)
            
            # STEP 2: TERRAFORM APPLY
            logger.info(f"[{instance_id}] Applying scenario: {scenario_name}")
            cmd = ["tofu", "apply", "-auto-approve", "-json"]
            
            # Inject scenario specific vars
            scenario_vars = self._extract_terraform_vars(scenario_config)
            for key, value in scenario_vars.items():
                cmd.extend(["-var", f"{key}={value}"])

            # Merge with user variable overrides
            if user_vars:
                for key, value in user_vars.items():
                    cmd.extend(["-var", f"{key}={value}"])
            
            # instance-specific naming...
            cmd.extend(["-var", f"vm_name=att-{instance_id[:8]}"])
            
            result = subprocess.run(
                cmd,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=1800  # 30 min max
            )
            
            if result.returncode != 0:
                # Capture last 2000 chars of error for debugging
                error_msg = result.stderr[-2000:] if result.stderr else "Unknown error"
                logger.error(f"[{instance_id}] Apply failed: {error_msg}")
                
                # CLEANUP FAILED WORKSPACE
                if work_dir.exists():
                    shutil.rmtree(work_dir)
                
                return {
                    "success": False, 
                    "error": f"Terraform apply failed: {error_msg}"
                }
            
            logger.info(f"[{instance_id}] Deployment successful")
            return {
                "success": True, 
                "outputs": self._get_outputs(work_dir)
            }
            
        except subprocess.TimeoutExpired:
            logger.error(f"[{instance_id}] Deployment timed out")
            if work_dir and work_dir.exists():
                shutil.rmtree(work_dir)
            return {
                "success": False,
                "error": "Deployment timed out (exceeded 30 minutes)"
            }
            
        except Exception as e:
            logger.error(f"[{instance_id}] Unexpected error: {str(e)}")
            if work_dir and work_dir.exists():
                shutil.rmtree(work_dir)
            return {
                "success": False,
                "error": str(e)
            }

    def destroy(self, instance_id: str):
        if self.mock_mode: 
            logger.info(f"[{instance_id}] 🎭 SIMULATING DESTROY...")
            return {"success": True}
        
        work_dir = RUNS_DIR / instance_id
        
        if not work_dir.exists():
            logger.warning(f"[{instance_id}] Workspace not found, nothing to destroy")
            return {"success": True}
        
        try:
            logger.info(f"[{instance_id}] Running terraform destroy...")
            result = subprocess.run(
                ["tofu", "destroy", "-auto-approve"],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=900  # 15 min
            )
            
            if result.returncode != 0:
                logger.error(f"[{instance_id}] Destroy failed: {result.stderr}")
                return {
                    "success": False,
                    "error": f"Terraform destroy failed: {result.stderr[-1000:]}"
                }
            
            # CLEANUP WORKSPACE
            shutil.rmtree(work_dir)
            logger.info(f"[{instance_id}] Workspace cleaned up")
            
            return {"success": True}
            
        except Exception as e:
            logger.error(f"[{instance_id}] Destroy error: {str(e)}")
            return {"success": False, "error": str(e)}
    

    def _get_outputs(self, work_dir: Path):
        """Read terraform outputs, flattened to {name: value}.

        `tofu output -json` wraps every output in {"value": ..., "type": ...};
        we unwrap here so DB/UI/consumers see one shape — the same one the
        mock outputs use.
        """
        try:
            res = subprocess.run(
                ["tofu", "output", "-json"],
                cwd=work_dir,
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )
            raw = json.loads(res.stdout)
            return {
                key: (entry.get("value") if isinstance(entry, dict) and "value" in entry else entry)
                for key, entry in raw.items()
            }
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to read terraform outputs in {work_dir}: {e}")
            return {}


    def _load_scenario(self, scenario_name: str) -> dict:
        """Load scenario YAML configuration"""
        import yaml

        from scenarios import is_valid_scenario_id

        # Defense in depth: the API already validates against the registry,
        # but this name becomes a filesystem path — never trust it here either.
        if not is_valid_scenario_id(scenario_name):
            logger.error(f"Rejected invalid scenario id: {scenario_name!r}")
            return None

        scenario_file = TEMPLATES_DIR / f"{scenario_name}.yaml"
        
        if not scenario_file.exists():
            logger.error(f"Scenario file not found: {scenario_file}")
            return None
        
        try:
            with open(scenario_file, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to load scenario {scenario_name}: {e}")
            return None

    def _extract_terraform_vars(self, scenario_config: dict) -> dict:
        """
        Extract Terraform variables from scenario YAML
        
        Maps scenario.yaml values to terraform variables:
        - vms[0].image → victim_image_name
        - vms[1].image → image_name (attacker)
        - vms[2].image → log_image_name (monitor)
        """
        vars = {}
        
        # Map VM definitions to Terraform variables
        for vm in scenario_config.get('vms', []):
            role = vm.get('role')
            
            if role == 'victim':
                vars['victim_image_name'] = vm.get('image', 'mrrobot-fixed')
                vars['victim_vm_name'] = vm.get('name', 'cyber_guard_victim')
                if 'flavor' in vm:
                    vars['flavor_name'] = vm['flavor']
            
            elif role == 'attacker':
                vars['image_name'] = vm.get('image', 'kali-linux-2025-cloud')
                vars['vm_name'] = vm.get('name', 'cyber_guard_attack')
            
            elif role == 'monitor':
                vars['log_image_name'] = vm.get('image', 'ubuntu_cloud')
                vars['log_vm_name'] = vm.get('name', 'cyber_guard_log')
                if 'flavor' in vm:
                    vars['soc_flavor_name'] = vm['flavor']
        
        # Network configuration
        if 'network' in scenario_config:
            net = scenario_config['network']
            if 'cidr' in net:
                vars['private_cidr'] = net['cidr']
        
        logger.info(f"Extracted Terraform vars: {vars}")
        return vars