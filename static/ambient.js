/* CSS handles motion; suspend it while the page is in the background. */
(() => {
 const scene=document.querySelector('.ambient-scene');
 if(!scene)return;
 const sync=()=>scene.classList.toggle('ambient-paused',document.hidden);
 document.addEventListener('visibilitychange',sync);
 sync();
})();
