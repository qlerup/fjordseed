(() => {
 'use strict';
 let audio, timer, lastQuack = 0;
 function quack() {
  if (!audio || audio.state !== 'running' || document.hidden || Date.now() - lastQuack < 450) return;
  lastQuack = Date.now();
  const start = audio.currentTime, pitch = 180 + Math.random() * 110;
  const count = 1 + Math.floor(Math.random() * 3);
  for (let i = 0; i < count; i++) {
   const at = start + i * .23, duration = .13 + Math.random() * .07;
   const voice = audio.createOscillator(), filter = audio.createBiquadFilter(), volume = audio.createGain();
   voice.type = 'sawtooth';
   voice.frequency.setValueAtTime(pitch * 1.35, at);
   voice.frequency.exponentialRampToValueAtTime(pitch * .75, at + duration);
   filter.type = 'bandpass'; filter.frequency.value = 1100 + Math.random() * 450; filter.Q.value = 1.8;
   volume.gain.setValueAtTime(0, at);
   volume.gain.linearRampToValueAtTime(.14, at + .015);
   volume.gain.exponentialRampToValueAtTime(.001, at + duration);
   voice.connect(filter); filter.connect(volume); volume.connect(audio.destination);
   voice.start(at); voice.stop(at + duration + .02);
   voice.onended = () => { voice.disconnect(); filter.disconnect(); volume.disconnect(); };
  }
 }
 function schedule() {
  clearTimeout(timer);
  if (!audio || document.hidden) return;
  timer = setTimeout(() => { quack(); schedule(); }, 18000 + Math.random() * 42000);
 }
 document.addEventListener('click', async event => {
  const button = event.target.closest('button, input[type="submit"], input[type="button"], [role="button"], .nav');
  if (!button || button.disabled || button.getAttribute('aria-disabled') === 'true') return;
  try {
   const Audio = window.AudioContext || window.webkitAudioContext;
   if (!Audio) return;
   audio ||= new Audio();
   if (audio.state === 'suspended') await audio.resume();
   quack(); schedule();
  } catch (_) { /* Optional sound must never interrupt an action. */ }
 }, {capture: true});
 document.addEventListener('visibilitychange', schedule);
 window.addEventListener('pagehide', () => { clearTimeout(timer); if (audio) audio.close().catch(() => {}); audio = null; });
})();
