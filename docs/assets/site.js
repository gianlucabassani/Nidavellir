// Site behaviour for docs/index.html. Kept in a file of its own because the domain's
// Content-Security-Policy only runs scripts served from the site, not inline ones.
document.documentElement.classList.add('js');

(function () {
  // Entrances: mark elements as they scroll into view. Without JS everything is visible.
  var reveals = document.querySelectorAll('.reveal');
  var stages = document.querySelectorAll('.stage');
  if (!('IntersectionObserver' in window)) {
    reveals.forEach(function (el) { el.classList.add('in'); });
    stages.forEach(function (el) { el.classList.add('lit'); });
  } else {
    var seen = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) { if (entry.isIntersecting) { entry.target.classList.add('in'); seen.unobserve(entry.target); } });
    }, { threshold: 0.12 });
    reveals.forEach(function (el) { seen.observe(el); });
    var lit = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) { if (entry.isIntersecting) { entry.target.classList.add('lit'); lit.unobserve(entry.target); } });
    }, { rootMargin: '0px 0px -38% 0px' });
    stages.forEach(function (el) { lit.observe(el); });
  }

  // Timeline: the gold spine fills as the reader moves through the stages.
  var timeline = document.getElementById('timeline');
  var frame = 0;
  function progress() {
    frame = 0;
    var box = timeline.getBoundingClientRect();
    var mark = window.innerHeight * 0.62;
    var value = Math.min(1, Math.max(0, (mark - box.top) / box.height));
    timeline.style.setProperty('--progress', value.toFixed(3));
  }
  function schedule() { if (!frame) frame = requestAnimationFrame(progress); }
  window.addEventListener('scroll', schedule, { passive: true });
  window.addEventListener('resize', schedule);
  progress();

  // Gallery tabs.
  var captions = {
    research: '<strong>Research.</strong> The session in progress, what needs an operator verdict, and the proof desk in one place.',
    session: '<strong>Session.</strong> A live arena: state, access gate, remaining action budget, the topology and the selected station.',
    audit: '<strong>Audit trail.</strong> Every event attributed to a human, an agent or the system, kept after the arena is gone.',
    range: '<strong>Cyber Range.</strong> The scenario catalog and the declared topology, reviewed before anything is launched.'
  };
  var tabs = Array.prototype.slice.call(document.querySelectorAll('.gallery-tabs [role="tab"]'));
  var shots = document.querySelectorAll('.frame-stage img');
  var stage = document.getElementById('gallery-stage');
  var caption = document.getElementById('gallery-caption');
  function show(tab, focus) {
    tabs.forEach(function (other) { var on = other === tab; other.setAttribute('aria-selected', String(on)); other.tabIndex = on ? 0 : -1; });
    shots.forEach(function (img) { img.classList.toggle('on', img.dataset.shot === tab.dataset.shot); });
    stage.setAttribute('aria-labelledby', tab.id);
    caption.innerHTML = captions[tab.dataset.shot];
    if (focus) tab.focus();
  }
  tabs.forEach(function (tab, index) {
    tab.addEventListener('click', function () { show(tab, false); });
    tab.addEventListener('keydown', function (event) {
      var step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
      if (!step) return;
      event.preventDefault();
      show(tabs[(index + step + tabs.length) % tabs.length], true);
    });
  });

  // Copy the quickstart commands.
  document.querySelectorAll('.copy').forEach(function (button) {
    var text = button.querySelector('span');
    button.addEventListener('click', function () {
      var done = function () { text.textContent = 'Copied'; setTimeout(function () { text.textContent = 'Copy'; }, 1800); };
      // The async clipboard needs HTTPS; the textarea route covers plain-HTTP previews.
      var legacy = function () {
        var area = document.createElement('textarea');
        area.value = button.dataset.copy; area.setAttribute('readonly', ''); area.style.position = 'fixed'; area.style.opacity = '0';
        document.body.appendChild(area); area.select();
        var ok = false; try { ok = document.execCommand('copy'); } catch (error) { ok = false; }
        document.body.removeChild(area);
        if (ok) done(); else text.textContent = 'Select and copy';
      };
      if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(button.dataset.copy).then(done, legacy);
      else legacy();
    });
  });
})();
