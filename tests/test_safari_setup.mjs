import test from 'node:test';
import assert from 'node:assert/strict';
import {isIPhoneSafari} from '../static/safari-setup.mjs';

const safari = 'Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1';

test('setup is available in normal iPhone Safari, including supported older iOS', () => {
  assert.equal(isIPhoneSafari({userAgent: safari}), true);
  assert.equal(isIPhoneSafari({userAgent: safari.replaceAll('26_0', '16_4').replaceAll('26.0', '16.4')}), true);
});

test('iOS home-screen/PWA modes do not offer Safari extension installation', () => {
  assert.equal(isIPhoneSafari({userAgent: safari, standalone: true}), false);
  assert.equal(isIPhoneSafari({userAgent: safari, displayModeStandalone: true}), false);
});

test('desktop, iPad, Android and alternative iPhone browsers stay hidden', () => {
  const excluded = [
    safari.replace('iPhone; CPU iPhone', 'iPad; CPU'),
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15',
    'Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36',
    safari.replace('Version/26.0', 'CriOS/130.0.0.0'),
    safari.replace('Version/26.0', 'FxiOS/131.0'),
    safari.replace('Version/26.0', 'EdgiOS/130.0'),
    safari + ' CriOS/130.0', safari + ' FxiOS/131.0', safari + ' EdgiOS/130.0',
    safari + ' [FBAN/FBIOS;FBAV/488.0]', safari + ' Instagram 354.0',
    safari + ' GSA/345.0', safari + ' Line/14.0',
    safari.replace('Version/26.0 ', '').replace(' Safari/604.1', ''),
    '',
  ];
  for (const userAgent of excluded) assert.equal(isIPhoneSafari({userAgent}), false, userAgent);
  assert.equal(isIPhoneSafari(), false);
});
