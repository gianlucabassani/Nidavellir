// Global Graph Instance
let cy = null;
let pollInterval = null;

document.addEventListener('DOMContentLoaded', function() {
    // 1. Check if we are on a specific dashboard page (by checking for the graph container)
    const graphContainer = document.getElementById('cy');
    
    if (graphContainer) {
        // We are on /dashboard/<instance_id>
        const instanceId = document.body.getAttribute('data-instance-id');
        
        if (instanceId) {
            console.log("Starting polling for instance:", instanceId);
            startPolling(instanceId);
            
            // Initial Render if data exists (LAB_DATA is injected by Jinja2 in dashboard.html)
            if (typeof LAB_DATA !== 'undefined' && LAB_DATA) {
                renderTopology(LAB_DATA);
            }
        }
    }
});

function startPolling(instanceId) {
    // Poll every 5 seconds
    pollInterval = setInterval(() => {
        fetch(`/api/poll/${instanceId}`)
            .then(response => response.json())
            .then(data => {
                updateStatusUI(data);

                // If instance becomes active but graph is empty (e.g. page refresh), reload to draw it
                if (!cy && data.status === 'active') {
                    window.location.reload(); 
                }
            })
            .catch(err => console.log("Poll error:", err));
    }, 5000);
}

function updateStatusUI(data) {
    const badge = document.getElementById('nav-status-badge');
    const text = document.getElementById('status-text');
    const spinner = document.getElementById('status-spinner');

    if (data.status === 'active') {
        // ONLINE
        if(badge) badge.className = "badge rounded-pill bg-success border border-success shadow-sm";
        if(text) text.innerText = "ONLINE";
        if(spinner) spinner.classList.add('d-none');
    } else if (data.status === 'deploying' || data.status === 'destroying' || data.status === 'pending') {
        // WORKING
        if(badge) badge.className = "badge rounded-pill bg-warning text-dark border border-warning shadow-sm";
        if(text) text.innerText = data.status.toUpperCase();
        if(spinner) { spinner.classList.remove('d-none'); }
    } else {
        // FAILED / OFFLINE
        if(badge) badge.className = "badge rounded-pill bg-danger border border-danger shadow-sm";
        if(text) text.innerText = data.status ? data.status.toUpperCase() : "OFFLINE";
        if(spinner) spinner.classList.add('d-none');
    }
}

// --- TOPOLOGY VISUALIZATION (CYTOSCAPE) ---
function renderTopology(data) {
    if(!document.getElementById('cy')) return;
    console.log("Rendering Topology...", data);

    const elements = [];

    // 1. INFRASTRUCTURE NODES (Static)
    elements.push({ data: { id: 'internet', label: 'Internet', color: '#6c757d', shape: 'cloud' } });
    elements.push({ data: { id: 'router', label: 'Gateway', color: '#198754', shape: 'rectangle' } });
    elements.push({ data: { id: 'subnet', label: 'Internal Net\n192.168.0.0/24', color: '#ffc107', shape: 'ellipse' } });

    // 2. INFRA EDGES
    elements.push({ data: { source: 'internet', target: 'router' } });
    elements.push({ data: { source: 'router', target: 'subnet' } });

    // 3. VM NODES
    
    // Attacker
    let attackIp = data.attacker_ip && data.attacker_ip.value ? data.attacker_ip.value : 'Provisioning...';
    elements.push({ 
        data: { 
            id: 'attacker', 
            label: 'Red Team\n' + attackIp, 
            color: '#dc3545', 
            shape: 'round-rectangle' 
        } 
    });
    elements.push({ data: { source: 'subnet', target: 'attacker' } });

    // Monitor / SOC
    let socIp = data.soc_ip && data.soc_ip.value ? data.soc_ip.value : 'Provisioning...';
    elements.push({ 
        data: { 
            id: 'soc', 
            label: 'Blue Team\n' + socIp, 
            color: '#0dcaf0', 
            shape: 'round-rectangle' 
        } 
    });
    elements.push({ data: { source: 'subnet', target: 'soc' } });

    // Victim
    let victimIp = data.victim_ip && data.victim_ip.value ? data.victim_ip.value : 'Provisioning...';
    elements.push({ 
        data: { 
            id: 'victim', 
            label: 'Target VM\n' + victimIp, 
            color: '#ffc107', 
            shape: 'round-rectangle' 
        } 
    });
    elements.push({ data: { source: 'subnet', target: 'victim' } });


    // 4. INIT CYTOSCAPE
    cy = cytoscape({
        container: document.getElementById('cy'),
        elements: elements,
        style: [
            {
                selector: 'node',
                style: {
                    'background-color': 'data(color)',
                    'label': 'data(label)',
                    'color': '#fff',
                    'text-outline-color': '#000',
                    'text-outline-width': 2,
                    'font-size': '13px',
                    'text-wrap': 'wrap',
                    'text-valign': 'center',
                    'text-halign': 'center',
                    'width': '120px',
                    'height': '60px',
                    'shape': 'data(shape)'
                }
            },
            {
                selector: 'edge',
                style: {
                    'width': 2,
                    'line-color': '#666',
                    'target-arrow-color': '#666',
                    'target-arrow-shape': 'triangle',
                    'curve-style': 'bezier'
                }
            }
        ],
        layout: {
            name: 'breadthfirst',
            directed: true,
            padding: 40,
            spacingFactor: 1.2,
            animate: false
        }
    });

    cy.resize();
    cy.fit();
}

function copyToClipboard(elementId) {
    var copyText = document.getElementById(elementId);
    if(copyText && copyText.value) {
        copyText.select();
        navigator.clipboard.writeText(copyText.value);
    }
}

function destroyInstance(instanceId) {
    if(!confirm("Destroy " + instanceId + "? This action is irreversible.")) return;
    
    fetch(`/api/destroy/${instanceId}`, {method: 'POST'})
    .then(() => {
        alert("Destroy started. Redirecting to lobby...");
        window.location.href = "/";
    })
    .catch(err => alert("Error: " + err));
}