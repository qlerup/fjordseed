from pathlib import Path
import base64
from playwright.sync_api import sync_playwright, expect
root=Path(__file__).resolve().parents[1]
with sync_playwright() as p:
 browser=p.chromium.launch()
 for width in (1440,390):
  page=browser.new_page(viewport={'width':width,'height':950})
  errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.clock.install()
  page.set_content('<html data-theme="viking"><body style="margin:0;background:#20383b"><div class="ambient-scene"></div><main><button id="battle-full-view">Fuld visning</button></main></body></html>')
  page.add_style_tag(content=(root/'static/ambient.css').read_text(encoding='utf-8-sig'))
  backdrop='data:image/svg+xml;base64,'+base64.b64encode((root/'static/viking-fjord.svg').read_bytes()).decode()
  page.add_style_tag(content=(root/'static/viking.css').read_text(encoding='utf-8-sig').replace('/static/viking-fjord.svg',backdrop))
  page.add_script_tag(content=(root/'static/viking-battle-model.js').read_text(encoding='utf-8-sig'))
  page.evaluate('''() => { let seed=71;const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};const Model=window.FjordBattleModel;window.FjordBattleModel=class extends Model {constructor(count){super(count,random,true);window.testBattle=this;}};}''')
  page.add_script_tag(content=(root/'static/viking-battle.js').read_text(encoding='utf-8-sig'))
  page.locator('#battle-full-view').click()
  expect(page.locator('body')).to_have_class('viking-full-view')
  assert page.locator('main').evaluate('e=>e.inert')
  def advance(seconds):
   page.evaluate('seconds=>{for(let i=0;i<seconds*20;i++)testBattle.advance(.05,innerWidth,innerHeight);dispatchEvent(new Event("resize"));}',seconds)
  expect(page.locator('.viking-settlement-house')).to_have_count(9)
  expect(page.locator('.village-fields')).to_have_count(1)
  assert page.locator('.village-resident.is-woman').count()>0
  assert page.locator('.village-resident:not(.is-woman)').count()>0
  assert page.locator('.village-resident.is-archer,.village-resident.is-spearman').count()==0
  assert page.locator('.viking-catapult').count()==0
  advance(12)
  page.screenshot(path=str(root/f'test-results/village-residents-{width}.png'))
  advance(page.evaluate('testBattle.arrivalEnd+3-testBattle.time'))
  assert page.evaluate('testBattle.units.filter(u=>u.civilian).every(u=>["running","offscreen"].includes(u.state))')
  for _ in range(300):
   if page.evaluate('testBattle.phase==="raid"'):break
   advance(.1)
  assert page.evaluate('testBattle.phase')=='raid'
  assert page.evaluate('testBattle.units.filter(u=>u.civilian).every(u=>u.state==="offscreen"&&u.deadAt===null)')
  for _ in range(150):
   if page.locator('.is-being-raided').count():break
   advance(.1)
  assert page.locator('.is-being-raided').count()>0
  assert page.evaluate('testBattle.units.filter(u=>u.state==="inside").every(u=>!u.civilian)')
  page.screenshot(path=str(root/f'test-results/village-raid-{width}.png'))
  advance(page.evaluate('testBattle.exitStart-testBattle.time-.1'))
  expect(page.locator('.has-loot .viking-loot').first).to_be_visible()
  before=page.evaluate('testBattle.round')
  advance(13.2)
  assert page.evaluate('testBattle.round')==before+1
  assert page.evaluate('testBattle.units.every(u=>!u.loot&&u.deadAt===null)')
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  assert not errors,errors
  page.close()
 browser.close()
print('PASS civilian men/women, village/farms, escape, Viking-only looting and restart on desktop/mobile')
