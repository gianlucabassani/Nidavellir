#!/bin/bash
#==============================================================================
# Script: setup_victim_agent.sh
# Descrizione: Installazione e configurazione Wazuh Agent per VM Vittima
#==============================================================================

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

set -euo pipefail

# Colori per output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Variabili configurabili per Cyber Range ITS
WAZUH_MANAGER_IP="${WAZUH_MANAGER_IP:-127.0.0.1}"
AGENT_NAME="${AGENT_NAME:-victim-$(hostname)}"
AGENT_GROUP="${AGENT_GROUP:-victim-servers}"
OS_TYPE="${OS_TYPE:-linux}"

# ... [IL RESTO DELLE FUNZIONI RIMANE INVARIATO, COPIA DALLO SCRIPT ORIGINALE] ...
# Per brevità qui metto solo la parte iniziale che è quella che dava errore.
# Assicurati di mantenere tutte le funzioni (install_wazuh_agent, configure_wazuh_agent, etc.)
# che c'erano nel file originale.

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "Questo script deve essere eseguito come root"
        exit 1
    fi
}

detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS_NAME=$ID
        OS_VERSION=$VERSION_ID
        log_success "Rilevato OS: $OS_NAME $OS_VERSION"
    else
        log_error "Impossibile rilevare il sistema operativo"
        exit 1
    fi
}

validate_manager_connectivity() {
    log_info "Verifica connettività con Wazuh Manager..."
    
    if ping -c 1 -W 3 "$WAZUH_MANAGER_IP" &>/dev/null; then
        log_success "Manager raggiungibile: $WAZUH_MANAGER_IP"
    else
        log_error "Impossibile raggiungere il Manager: $WAZUH_MANAGER_IP"
        log_info "Verifica la connettività di rete e l'IP del Manager"
        exit 1
    fi
    
    # Verifica porta 1514 (agent communication)
    if nc -z -w 3 "$WAZUH_MANAGER_IP" 1514; then
        log_success "Porta 1514 raggiungibile sul Manager"
    else
        log_warning "Porta 1514 non raggiungibile - verifica configurazione Manager"
    fi
}

install_wazuh_agent() {
    log_info "Installazione Wazuh Agent..."
    
    case $OS_NAME in
        ubuntu|debian)
            install_wazuh_agent_debian
            ;;
        centos|rhel|rocky)
            install_wazuh_agent_rhel
            ;;
        *)
            log_error "Sistema operativo non supportato: $OS_NAME"
            exit 1
            ;;
    esac
}

install_wazuh_agent_debian() {
    log_info "Installazione su sistema Debian-based..."
    apt-get update
    apt-get install -y curl gnupg lsb-release
    curl -s https://packages.wazuh.com/key/GPG-KEY-WAZUH | gpg --no-default-keyring --keyring gnupg-ring:/usr/share/keyrings/wazuh.gpg --import
    chmod 644 /usr/share/keyrings/wazuh.gpg
    echo "deb [signed-by=/usr/share/keyrings/wazuh.gpg] https://packages.wazuh.com/4.x/apt/ stable main" | tee /etc/apt/sources.list.d/wazuh.list
    apt-get update
    WAZUH_MANAGER="$WAZUH_MANAGER_IP" apt-get install -y wazuh-agent
    log_success "Wazuh Agent installato su sistema Debian"
}

install_wazuh_agent_rhel() {
    log_info "Installazione su sistema RHEL-based..."
    cat > /etc/yum.repos.d/wazuh.repo << EOF
[wazuh]
name=Wazuh repository
baseurl=https://packages.wazuh.com/4.x/yum/
gpgcheck=1
gpgkey=https://packages.wazuh.com/key/GPG-KEY-WAZUH
enabled=1
EOF
    WAZUH_MANAGER="$WAZUH_MANAGER_IP" yum install -y wazuh-agent
    log_success "Wazuh Agent installato su sistema RHEL"
}

configure_wazuh_agent() {
    log_info "Configurazione Wazuh Agent..."
    local ossec_config="/var/ossec/etc/ossec.conf"
    local backup_file="${ossec_config}.backup.$(date +%Y%m%d_%H%M%S)"
    cp "$ossec_config" "$backup_file"
    
    cat > "$ossec_config" << EOF
<ossec_config>
  <client>
    <server>
      <address>$WAZUH_MANAGER_IP</address>
      <port>1514</port>
      <protocol>udp</protocol>
      <notify_time>10</notify_time>
      <time-reconnect>60</time-reconnect>
    </server>
    <config-profile>$OS_TYPE, $OS_NAME, $OS_NAME$OS_VERSION</config-profile>
    <server-ip>$WAZUH_MANAGER_IP</server-ip>
  </client>
  <client_buffer>
    <disabled>no</disabled>
    <queue_size>5000</queue_size>
    <events_per_second>500</events_per_second>
  </client_buffer>
  <syscheck>
    <disabled>no</disabled>
    <frequency>180</frequency>
    <scan_on_start>yes</scan_on_start>
    <auto_ignore>yes</auto_ignore>
    <alert_new_files>yes</alert_new_files>
    <directories check_all="yes" realtime="yes">/etc</directories>
    <directories check_all="yes">/bin,/sbin,/usr/bin,/usr/sbin</directories>
    <directories check_all="yes">/var/www,/opt,/home</directories>
    <ignore>/etc/mtab</ignore>
    <ignore>/etc/hosts.deny</ignore>
    <ignore>/var/log</ignore>
    <ignore>/var/run</ignore>
    <ignore>/tmp</ignore>
    <ignore>/dev</ignore>
    <ignore>/proc</ignore>
    <ignore type="sregex">.log$|.swp$|.tmp$</ignore>
  </syscheck>
  <localfile>
    <log_format>syslog</log_format>
    <location>/var/log/auth.log</location>
  </localfile>
  <localfile>
    <log_format>syslog</log_format>
    <location>/var/log/syslog</location>
  </localfile>
  <localfile>
    <log_format>syslog</log_format>
    <location>/var/log/kern.log</location>
  </localfile>
  <localfile>
    <log_format>syslog</log_format>
    <location>/var/log/dpkg.log</location>
  </localfile>
  <localfile>
    <log_format>apache</log_format>
    <location>/var/log/apache2/access.log</location>
  </localfile>
  <localfile>
    <log_format>apache</log_format>
    <location>/var/log/apache2/error.log</location>
  </localfile>
  <rootcheck>
    <disabled>no</disabled>
    <check_files>yes</check_files>
    <check_trojans>yes</check_trojans>
    <check_dev>yes</check_dev>
    <check_sys>yes</check_sys>
    <check_pids>yes</check_pids>
    <check_ports>yes</check_ports>
    <check_if>yes</check_if>
    <frequency>43200</frequency>
  </rootcheck>
  <active-response>
    <disabled>no</disabled>
    <ca_store>/var/ossec/wodles/cacert.pem</ca_store>
  </active-response>
</ossec_config>
EOF
    echo "$AGENT_NAME" > /var/ossec/etc/client.keys
    chown root:wazuh /var/ossec/etc/client.keys
    chmod 640 /var/ossec/etc/client.keys
    log_success "Configurazione Wazuh Agent completata"
}

register_agent() {
    log_info "Registrazione Agent con il Manager..."
    if [ -f /var/ossec/etc/client.keys ]; then
        mv /var/ossec/etc/client.keys /var/ossec/etc/client.keys.backup
    fi
    systemctl start wazuh-agent
    local max_attempts=30
    local attempt=1
    while [ $attempt -le $max_attempts ]; do
        if [ -f /var/ossec/etc/client.keys ] && [ -s /var/ossec/etc/client.keys ]; then
            local agent_id=$(awk '{print $2}' /var/ossec/etc/client.keys)
            log_success "Agent registrato con ID: $agent_id"
            return 0
        fi
        log_info "Tentativo $attempt/$max_attempts - Attesa registrazione..."
        sleep 3
        ((attempt++))
    done
    log_warning "Timeout durante la registrazione - verifica manualmente"
    return 1
}

start_agent_services() {
    log_info "Avvio servizi Wazuh Agent..."
    systemctl daemon-reload
    systemctl enable wazuh-agent
    systemctl restart wazuh-agent
    sleep 3
    if systemctl is-active --quiet wazuh-agent; then
        log_success "Wazuh Agent avviato correttamente"
    else
        log_error "Errore nell'avvio di Wazuh Agent"
        journalctl -u wazuh-agent -n 50 --no-pager
        exit 1
    fi
}

test_agent_configuration() {
    log_info "Test configurazione Agent..."
    if /var/ossec/bin/verify-agent-conf; then
        log_success "Configurazione Agent valida"
    else
        log_error "Errore nella configurazione Agent"
        exit 1
    fi
    if grep -q "$WAZUH_MANAGER_IP" /var/ossec/etc/client.keys 2>/dev/null; then
        log_success "Agent configurato per Manager: $WAZUH_MANAGER_IP"
    else
        log_warning "Agent non correttamente configurato per il Manager"
    fi
}

create_agent_monitoring_script() {
    log_info "Creazione script di monitoraggio Agent..."
    cat > /usr/local/bin/agent_status.sh <<'EOFSCRIPT'
#!/bin/bash
echo "AGENT STATUS"
if [ -f /var/ossec/etc/client.keys ]; then
    cat /var/ossec/etc/client.keys
else
    echo "Agent non registrato"
fi
echo "Service: $(systemctl is-active wazuh-agent)"
EOFSCRIPT
    chmod +x /usr/local/bin/agent_status.sh
    log_success "Script di monitoraggio creato"
}

main() {
    echo "=== SETUP VICTIM AGENT ==="
    check_root
    detect_os
    
    if [ -z "$WAZUH_MANAGER_IP" ] || [ "$WAZUH_MANAGER_IP" = "127.0.0.1" ]; then
        log_error "WAZUH_MANAGER_IP non configurato"
        exit 1
    fi
    
    validate_manager_connectivity
    install_wazuh_agent
    configure_wazuh_agent
    start_agent_services
    register_agent
    test_agent_configuration
    create_agent_monitoring_script
    
    log_success "INSTALLAZIONE COMPLETATA"
}

main "$@"

