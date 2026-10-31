from pathlib import Path
import base64
from playwright.sync_api import sync_playwright, expect
root=Path(__file__).resolve().parents[1]
with sync_playwright() as p:
 browser=p.chromium.launch()
 for width in (1440,390):
  page=browser.new_page(viewport={'width':width,'height':950})
  errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.clock.install(time=0)
  page.clock.pause_at(1000)
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
  visible_fall=False
  house_symbols=set()
  hidden_resident=False
  for _ in range(1200):
   if page.locator('.village-resident.is-fallen:not([hidden])').count():
    visible_fall=True
    expect(page.locator('.village-resident.is-fallen:not([hidden])').first).to_be_visible()
   for symbol in ('hearts','skulls'):
    if symbol not in house_symbols and page.locator(f'.has-{symbol}').count():
     house_symbols.add(symbol)
     expect(page.locator(f'.has-{symbol} .house-{symbol} svg').first).to_be_visible()
     page.screenshot(path=str(root/f'test-results/village-{symbol}-{width}.png'))
   hidden_id=page.evaluate('testBattle.units.find(u=>u.civilian&&u.state==="hiding")?.id')
   if hidden_id is not None:
    hidden_resident=True
    expect(page.locator('.viking-warrior').nth(hidden_id)).to_be_hidden()
   assert page.evaluate('testBattle.units.filter(u=>u.civilian).every(u=>u.x>=.025&&u.x<=.64&&u.state!=="offscreen")')
   if page.evaluate('testBattle.phase==="raid"'):break
   advance(.1)
  assert page.evaluate('testBattle.phase')=='raid'
  assert page.evaluate('testBattle.units.some(u=>u.civilian&&u.deadAt!==null)')
  assert visible_fall
  assert hidden_resident and house_symbols=={'hearts','skulls'}
  assert page.evaluate('testBattle.units.filter(u=>u.civilian).every(u=>u.deadAt!==null||u.sheltered)')
  for _ in range(150):
   if page.locator('.is-being-raided').count():break
   advance(.1)
  assert page.locator('.is-being-raided').count()>0
  assert page.evaluate('testBattle.units.filter(u=>u.state==="inside").every(u=>!u.civilian)')
  page.screenshot(path=str(root/f'test-results/village-raid-{width}.png'))
  advance(page.evaluate('testBattle.exitStart-testBattle.time-.1'))
  expect(page.locator('.has-loot .viking-loot').first).to_be_visible()
  before=page.evaluate('testBattle.round')
  advance(2)
  assert page.evaluate('testBattle.phase')=='boarding'
  expect(page.locator('.has-loot .viking-loot').first).to_be_visible()
  page.screenshot(path=str(root/f'test-results/village-return-{width}.png'))
  for _ in range(120):
   if page.evaluate('testBattle.phase==="departure"'):break
   advance(.2)
  assert page.evaluate('testBattle.units.filter(u=>u.team===1&&u.deadAt===null&&!u.withdrawing).every(u=>u.state==="aboard")')
  expect(page.locator('.has-loot .viking-loot').first).to_be_visible()
  advance(8)
  assert page.evaluate('testBattle.boats.every(b=>b.y<b.dockY&&b.scale<.63)')
  page.screenshot(path=str(root/f'test-results/village-departure-{width}.png'))
  advance(page.evaluate('testBattle.departureEnd-testBattle.time-.5'))
  assert page.locator('.viking-longship:not([hidden])').count()==0
  advance(.6)
  assert page.evaluate('testBattle.round')==before+1
  assert page.evaluate('testBattle.units.every(u=>!u.loot&&u.deadAt===null)')
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  assert not errors,errors
  page.close()
 browser.close()
print('PASS bounded panic, hidden residents, hearts/skulls, lethal pursuit, looting and restart on desktop/mobile')
