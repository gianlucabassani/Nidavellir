// This public calibration UI deliberately supplies two synthetic test identities.
// Object content is obtained by client-side fetch; the HTML contains no object data.
const tokens = {A: 'token-a-public', B: 'token-b-operator'};
const select = document.querySelector('#account');
const status = document.querySelector('#status');
const output = document.querySelector('#object');
const requested = new URLSearchParams(location.search).get('account');
select.value = requested === 'B' ? 'B' : 'A';

async function loadObject() {
  const account = select.value;
  history.replaceState(null, '', `/?account=${account}`);
  const requestId = `spa${Date.now()}${Math.floor(Math.random() * 1000000)}`;
  const response = await fetch(`/protected/${account}`, {
    headers: {Authorization: `Bearer ${tokens[account]}`, 'X-Request-ID': requestId},
  });
  const body = await response.json();
  status.textContent = response.ok ? `Account ${account} owns an object` : 'Object unavailable';
  output.textContent = JSON.stringify(body, null, 2);
}
select.addEventListener('change', loadObject);
loadObject().catch(() => { status.textContent = 'Object unavailable'; });
