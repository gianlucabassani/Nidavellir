#!/bin/bash
# user_data/soc_install.sh - Script di installazione automatica SOC (FINAL FIX)

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

# Variabili Terraform (Queste vengono sostituite da Terraform)
NET_IF="${network_interface}"
H_NET="${home_net}"

# Log dell'installazione
exec > >(tee /var/log/soc_installation.log) 2>&1

echo "=== INIZIO INSTALLAZIONE AUTOMATICA SOC ==="
apt-get update && apt-get install -y curl jq tar libcap2-bin software-properties-common

# -----------------------------------------------------------------------------
# 1. INSTALLAZIONE WAZUH (Metodo Ufficiale All-in-One)
# -----------------------------------------------------------------------------
echo "--> Installazione Wazuh All-in-One..."

curl -sO https://packages.wazuh.com/4.9/wazuh-install.sh
bash wazuh-install.sh -a -i

tar -xf wazuh-install-files.tar
if [ -f wazuh-install-files/wazuh-passwords.txt ]; then
    echo "--> Credenziali salvate in /root/wazuh-passwords.txt"
    cat wazuh-install-files/wazuh-passwords.txt > /root/wazuh-passwords.txt
fi

# -----------------------------------------------------------------------------
# 2. INSTALLAZIONE SURICATA
# -----------------------------------------------------------------------------
echo "--> Installazione Suricata..."
add-apt-repository -y ppa:oisf/suricata-stable
apt-get update
apt-get install -y suricata

# Configurazione Suricata
echo "--> Configurazione Suricata..."

# Creiamo il file di config con i placeholder
cat > /etc/suricata/suricata.yaml <<'EOF'
%YAML 1.1
---
vars:
  address-groups:
    HOME_NET: "[__HOME_NET__]"
    EXTERNAL_NET: "!$HOME_NET"
    HTTP_SERVERS: "$HOME_NET"
    SMTP_SERVERS: "$HOME_NET"
    SQL_SERVERS: "$HOME_NET"
    DNS_SERVERS: "$HOME_NET"
    TELNET_SERVERS: "$HOME_NET"
    AIM_SERVERS: "$EXTERNAL_NET"
    DC_SERVERS: "$HOME_NET"
    DNP3_SERVER: "$HOME_NET"
    DNP3_CLIENT: "$HOME_NET"
    MODBUS_CLIENT: "$HOME_NET"
    MODBUS_SERVER: "$HOME_NET"
    ENIP_CLIENT: "$HOME_NET"
    ENIP_SERVER: "$HOME_NET"

default-log-dir: /var/log/suricata/
stats:
  enabled: yes
  interval: 8

outputs:
  - fast:
      enabled: yes
      filename: fast.log
      append: yes
  - eve-log:
      enabled: yes
      filetype: regular
      filename: eve.json
      types:
        - alert
        - http:
            extended: yes
        - dns
        - tls:
            extended: yes
        - files:
            force-magic: yes
            force-hash: [md5]
        - ssh
      community-id: true

af-packet:
  - interface: __INTERFACE__
    cluster-id: 99
    cluster-type: cluster_flow
    defrag: yes

app-layer:
  protocols:
    krwb:
      enabled: yes
    dnp3:
      enabled: yes
    modbus:
      enabled: yes
    enip:
      enabled: yes

pcap:
  - interface: __INTERFACE__

default-rule-path: /var/lib/suricata/rules
rule-files:
  - suricata.rules
EOF

# Sostituiamo i placeholder con i valori reali usando sed
# Usiamo il pipe | come delimitatore per evitare problemi con gli slash negli IP
sed -i "s|__INTERFACE__|$NET_IF|g" /etc/suricata/suricata.yaml
sed -i "s|__HOME_NET__|$H_NET|g" /etc/suricata/suricata.yaml

# Aggiornamento regole e permessi
suricata-update
chown -R suricata:suricata /var/log/suricata

# -----------------------------------------------------------------------------
# 3. INTEGRAZIONE SURICATA -> WAZUH
# -----------------------------------------------------------------------------
echo "--> Integrazione Wazuh..."

if ! grep -q "eve.json" /var/ossec/etc/ossec.conf; then
    cat >> /var/ossec/etc/ossec.conf << EOF
<ossec_config>
  <localfile>
    <log_format>json</log_format>
    <location>/var/log/suricata/eve.json</location>
  </localfile>
</ossec_config>
EOF
fi

systemctl restart wazuh-manager
systemctl enable suricata
systemctl restart suricata

# -----------------------------------------------------------------------------
# 4. MONITOR SCRIPT
# -----------------------------------------------------------------------------
cat > /usr/local/bin/soc_status.sh <<'EOFSCRIPT'
#!/bin/bash
echo "=== SOC STATUS ==="
echo "Wazuh Manager: $(systemctl is-active wazuh-manager)"
echo "Wazuh Dashboard: $(systemctl is-active wazuh-dashboard)"
echo "Suricata: $(systemctl is-active suricata)"
echo ""
echo "Credenziali Wazuh:"
if [ -f /root/wazuh-passwords.txt ]; then
    cat /root/wazuh-passwords.txt
else
    echo "Password file not found."
fi
EOFSCRIPT
chmod +x /usr/local/bin/soc_status.sh

# -----------------------------------------------------------------------------
# 5. MINIO INSTALLATION (Standalone)
# -----------------------------------------------------------------------------
echo "--> Installazione MinIO..."
wget -q https://dl.min.io/server/minio/release/linux-amd64/minio
chmod +x minio
mv minio /usr/local/bin/

# Evita errore se utente esiste già
useradd -r minio-user -s /sbin/nologin || true
mkdir -p /mnt/data/reports
chown -R minio-user:minio-user /mnt/data

cat > /etc/systemd/system/minio.service <<EOF
[Unit]
Description=MinIO
Documentation=https://docs.min.io
Wants=network-online.target
After=network-online.target

[Service]
User=minio-user
Group=minio-user
Environment="MINIO_ROOT_USER=cyberadmin"
Environment="MINIO_ROOT_PASSWORD=CyberRangeStorage2024!"
ExecStart=/usr/local/bin/minio server /mnt/data --console-address ":9001"
Restart=always
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable minio
systemctl start minio

echo "=== INSTALLAZIONE COMPLETATA SUCCESSO ==="