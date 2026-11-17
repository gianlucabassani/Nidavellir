#!/usr/bin/env python3
"""
Setup automatico macchina attaccante
Installa e configura tutti i tool necessari
"""

import subprocess
import sys
import os
from datetime import datetime

LOG_FILE = "/tmp/attacker_setup.log"

# Tool da installare
REQUIRED_PACKAGES = [
    "nmap",
    "nikto", 
    "hydra",
    "sqlmap",
    "git",
    "curl",
    "wget",
    "python3-pip",
    "net-tools",
    "dnsutils"
]

# Pacchetti Python
PYTHON_PACKAGES = [
    "requests",
    "urllib3",
    "beautifulsoup4",
    "lxml"
]

def log_event(message, level="INFO"):
    """Log eventi"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] [{level}] {message}"
    print(log_msg)
    
    with open(LOG_FILE, "a") as f:
        f.write(log_msg + "\n")

def print_banner():
    """Banner iniziale"""
    banner = """
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║         SETUP MACCHINA ATTACCANTE - CYBER RANGE          ║
    ║         Installazione automatica tool offensivi           ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    print(banner)

def check_root():
    """Verifica privilegi root"""
    if os.geteuid() != 0:
        log_event("ERRORE: Questo script richiede privilegi root", "ERROR")
        log_event("Esegui con: sudo python3 setup_attacker.py", "ERROR")
        sys.exit(1)
    else:
        log_event("Privilegi root verificati ✓")

def run_command(command, description, critical=True):
    """Esegue comando shell con logging"""
    log_event(f"Esecuzione: {description}")
    log_event(f"Comando: {command}")
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=600
        )
        
        if result.returncode == 0:
            log_event(f"✓ {description} completato con successo")
            if result.stdout:
        else:
            log_event(f"✗ {description} fallito (exit code: {result.returncode})", "ERROR")
            if result.stderr:
                log_event(f"Errore: {result.stderr[:500]}", "ERROR")
            

            if critical:
                log_event("Operazione critica fallita, interruzione setup", "ERROR")
                sys.exit(1)
            return False
            

    except subprocess.TimeoutExpired:
        log_event(f"✗ Timeout durante: {description}", "ERROR")

        if critical:
            sys.exit(1)
        return False
    except Exception as e:

        log_event(f"✗ Eccezione durante {description}: {e}", "ERROR")
        if critical:
            sys.exit(1)
        return False

def update_system():
    """Aggiorna il sistema"""
    log_event("="*60)

    log_event("FASE 1: Aggiornamento sistema")
    log_event("="*60)
    
    # Update package list
    run_command(
        "apt-get update",
        "Aggiornamento lista pacchetti",

        critical=True
    )
    
    # Upgrade system (non critico, può richiedere molto tempo)
    run_command(

        "apt-get upgrade -y",
        "Upgrade sistema",
        critical=False
    )

def install_packages():
    """Installa pacchetti richiesti"""
    log_event("="*60)
    log_event("FASE 2: Installazione tool offensivi")
    log_event("="*60)
    
    for package in REQUIRED_PACKAGES:
        run_command(
            f"apt-get install -y {package}",
            f"Installazione {package}",
            critical=False
        )

def install_python_packages():
    """Installa pacchetti Python"""
    log_event("="*60)
    log_event("FASE 3: Installazione librerie Python")
    log_event("="*60)
    
        )
        "echo 1 > /proc/sys/net/ipv4/ip_forward",
        "Abilitazione IP forwarding",
    # Verifica connettività
    run_command(
        "ping -c 3 8.8.8.8",

def create_attack_scripts():
    """Crea directory per gli script"""
    log_event("="*60)
    log_event("FASE 5: Setup directory script")
    log_event("="*60)
    
    attack_dir = "/opt/cyber-range-attacks"
    
    try:
        if not os.path.exists(attack_dir):
            os.makedirs(attack_dir)
            log_event(f"Directory creata: {attack_dir}")
        else:
            log_event(f"Directory già esistente: {attack_dir}")
        
        # Crea sottodirectory
        subdirs = ["logs", "reports", "payloads", "wordlists"]
        for subdir in subdirs:
            path = f"{attack_dir}/{subdir}"
            if not os.path.exists(path):
                os.makedirs(path)
                log_event(f"Sottodirectory creata: {path}")
        
        # Crea symlink in /tmp per facilità
        tmp_link = "/tmp/attacks"
        if not os.path.exists(tmp_link):
            os.symlink(attack_dir, tmp_link)
            log_event(f"Symlink creato: {tmp_link} -> {attack_dir}")
        
        return attack_dir
        
    except Exception as e:
        log_event(f"Errore creazione directory: {e}", "ERROR")
        return None

def create_wordlists():
    """Crea wordlist base per bruteforce"""
        "654321", "superman", "qazwsx", "michael", "football",
        "admin", "root", "toor", "test", "guest",
        "user", "admin123", "password123", "welcome", "login"
        "admin", "administrator", "root", "user", "test",
        "guest", "demo", "webmaster", "operator", "support"
        # Password wordlist
        
        # Username wordlist
        with open("/tmp/usernames.txt", "w") as f:
            f.write("\n".join(usernames))
        log_event(f"Wordlist username creata: /tmp/usernames.txt ({len(usernames)} entries)")
        
    except Exception as e:
        log_event(f"Errore creazione wordlist: {e}", "ERROR")

    log_event("FASE 7: Verifica installazione")
    log_event("="*60)
    
    tools_to_check = {
        "nmap": "nmap --version",
        "nikto": "nikto -Version",
        "hydra": "hydra -h",
        "python3": "python3 --version",
        "pip3": "pip3 --version"
    }
    
    results = {}
    
    for tool, command in tools_to_check.items():
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                log_event(f"✓ {tool} installato correttamente")
                results[tool] = True
            else:
                log_event(f"✗ {tool} NON trovato", "WARNING")
                results[tool] = False
                
        except Exception as e:
            log_event(f"✗ Errore verifica {tool}: {e}", "WARNING")
            results[tool] = False
    
    return results

def generate_setup_report(results):
    """Genera report del setup"""
    log_event("="*60)
    log_event("GENERAZIONE REPORT FINALE")
    log_event("="*60)
    
    report = f"""
{'='*70}
REPORT SETUP MACCHINA ATTACCANTE
{'='*70}
Data/Ora: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Sistema: Kali Linux / Debian-based

TOOL INSTALLATI:
"""
    
    for tool, installed in results.items():
        status = "✓ INSTALLATO" if installed else "✗ NON INSTALLATO"
        report += f"  {tool:20s} {status}\n"
    
    report += f"""
{'='*70}
DIRECTORY CREATE:
  - /opt/cyber-range-attacks/
  - /opt/cyber-range-attacks/logs/
  - /opt/cyber-range-attacks/reports/
  - /opt/cyber-range-attacks/payloads/
  - /opt/cyber-range-attacks/wordlists/
  - /tmp/attacks/ (symlink)

FILE CREATI:
  - /tmp/passwords.txt (wordlist password)
  - /tmp/usernames.txt (wordlist username)
  - {LOG_FILE} (log setup)

CONFIGURAZIONI:
  - IP forwarding: ABILITATO
  - Network: CONFIGURATA

PROSSIMI PASSI:
  1. Copiare gli script di attacco in /opt/cyber-range-attacks/
  2. Configurare gli IP target negli script
  3. Eseguire: python3 attack_orchestrator.py

{'='*70}
"""
    
    print(report)
    
    # Salva report
    with open("/tmp/setup_report.txt", "w") as f:
        f.write(report)
    
    log_event("Report salvato: /tmp/setup_report.txt")

def create_launcher_script():
    """Crea script di lancio rapido"""
    log_event("="*60)
    log_event("FASE 8: Creazione launcher script")
    log_event("="*60)
    
    launcher_content = """#!/bin/bash
# Quick launcher per attacchi Cyber Range

echo "╔═══════════════════════════════════════════╗"
echo "║   CYBER RANGE - ATTACK LAUNCHER          ║"
echo "╚═══════════════════════════════════════════╝"
echo ""
echo "Seleziona attacco:"
echo "  1) Enumerazione e Port Scan"
echo "  2) Web Vulnerability Scan"
echo "  3) Bruteforce Login"
echo "  4) Campagna Completa (tutti gli attacchi)"
echo "  5) Exit"
echo ""
read -p "Scelta [1-5]: " choice

case $choice in
    1)
        echo "Avvio enumerazione..."
        python3 /opt/cyber-range-attacks/enum_portscan.py
        ;;
    2)
        echo "Avvio web scan..."
        python3 /opt/cyber-range-attacks/web_vulnerability_scan.py
        ;;
    3)
        echo "Avvio bruteforce..."
        python3 /opt/cyber-range-attacks/web_bruteforce.py
        ;;
    4)
        echo "Avvio campagna completa..."
        python3 /opt/cyber-range-attacks/attack_orchestrator.py
        ;;
    5)
        echo "Exit"
        exit 0
        ;;
    *)
        echo "Scelta non valida"
        exit 1
        ;;
esac
"""
    
    try:
        with open("/usr/local/bin/cyber-attack", "w") as f:
            f.write(launcher_content)
        
        os.chmod("/usr/local/bin/cyber-attack", 0o755)
        log_event("✓ Launcher creato: /usr/local/bin/cyber-attack")
        log_event("Usa comando 'cyber-attack' per lanciare gli attacchi")
        
    except Exception as e:
        log_event(f"Errore creazione launcher: {e}", "WARNING")

def main():
    """Main execution"""
    print_banner()
    
    log_event("="*70)
    log_event("INIZIO SETUP MACCHINA ATTACCANTE")
    log_event("="*70)
    
    # Check root
    check_root()
    
    # Fasi setup
    update_system()
    install_packages()
    install_python_packages()
    configure_network()
    create_attack_scripts()
    create_wordlists()
    create_launcher_script()
    
    # Verifica installazione
    results = verify_installation()
    
    # Report finale
    generate_setup_report(results)
    
    log_event("="*70)
    log_event("SETUP COMPLETATO!")
    log_event("="*70)
    
    print("\n" + "="*70)
    print("✓ SETUP COMPLETATO CON SUCCESSO!")
    print("="*70)
    print("\nPROSSIMI PASSI:")
    print("  1. Copia gli script di attacco in /opt/cyber-range-attacks/")
    print("  2. Modifica gli IP target negli script")
    print("  3. Lancia gli attacchi con: cyber-attack")
    print(f"\nLog completo: {LOG_FILE}")
    print("Report setup: /tmp/setup_report.txt")
    print("="*70)

if __name__ == "__main__":
    main()def verify_installation():
    """Verifica che i tool siano installati correttamente"""
    log_event("="*60)
        with open("/tmp/passwords.txt", "w") as f:
            f.write("\n".join(passwords))
        log_event(f"Wordlist password creata: /tmp/passwords.txt ({len(passwords)} entries)")
    ]
    
    try:
    ]
    
    usernames = [
    log_event("="*60)
        "baseball", "111111", "iloveyou", "master", "sunshine",
        "ashley", "bailey", "passw0rd", "shadow", "123123",
    log_event("FASE 6: Creazione wordlist")
    log_event("="*60)
        "monkey", "1234567", "letmein", "trustno1", "dragon",
    
    passwords = [
        "password", "123456", "12345678", "qwerty", "abc123",
        "Test connettività Internet",
        critical=False
    )
        critical=False
    )
    
    
    # Abilita IP forwarding (utile per MITM)
    run_command(
    log_event("="*60)
    log_event("FASE 4: Configurazione rete")
    log_event("="*60)

def configure_network():
    """Configurazione rete base"""
            f"pip3 install {package}",
            f"Installazione {package}",
            critical=False
    # Upgrade pip
    for package in PYTHON_PACKAGES:
        run_command(
        critical=False
    )
    
    run_command(
        "pip3 install --upgrade pip",
        "Upgrade pip",

